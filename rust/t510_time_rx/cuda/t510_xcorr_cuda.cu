#include <cuda_runtime.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

namespace fs = std::filesystem;

namespace {

constexpr std::size_t kBlockCount = 16;
constexpr std::size_t kChannelsPerBlock = 256;
constexpr std::size_t kGlobalBins = 4096;
constexpr std::size_t kAdcCount = 8;
constexpr std::size_t kPairCount = 28;
constexpr std::size_t kProductCount = kAdcCount + kPairCount;
constexpr std::size_t kRingSlots = 32768;
constexpr std::size_t kHeaderBytes = 4096;
constexpr std::size_t kSlotHeaderBytes = 64;
constexpr std::size_t kPayloadBytes = 8192;
constexpr std::size_t kPayloadInt16 = kPayloadBytes / sizeof(std::int16_t);
constexpr std::size_t kSlotBytes = kSlotHeaderBytes + kPayloadBytes;
constexpr std::uint64_t kRingMagic = 0x3152435835333554ULL;
constexpr std::uint64_t kRingVersion = 1;
constexpr std::uint64_t kSampleStep = 4096;
constexpr std::uint64_t kSampleRate = 320000000;
constexpr std::uint64_t kFocusTicks = 32000000;
constexpr std::uint64_t kPfbActive = 1ULL << 10;
constexpr std::uint64_t kFftOnly = 1ULL << 8;
constexpr std::size_t kMaxBatch = 512;
// Four adjacent channels share one CUDA block. Their eight complex inputs are
// loaded from staged global memory once per spectrum and then reused by all
// 36 auto/cross product threads. Time is tiled so each block needs only 4 KiB
// of shared memory at the 32-frame tile, preserving high SM occupancy.
constexpr std::size_t kCudaChannelsPerBlock = 4;
constexpr std::size_t kCudaTimeTile = 32;
constexpr std::size_t kCudaThreads = kProductCount * kCudaChannelsPerBlock;
static_assert(kChannelsPerBlock % kCudaChannelsPerBlock == 0,
              "CUDA channel tile must not straddle a PFB block");
static_assert(kCudaThreads <= 1024, "CUDA product tile exceeds block size");

constexpr std::size_t H_MAGIC = 0;
constexpr std::size_t H_VERSION = 8;
constexpr std::size_t H_STATE = 16;
constexpr std::size_t H_CANCEL = 24;
constexpr std::size_t H_FAILED = 32;
constexpr std::size_t H_START_SAMPLE0 = 40;
constexpr std::size_t H_END_SAMPLE0 = 48;
constexpr std::size_t H_COMPLETED_MASK = 56;
constexpr std::size_t H_GENERATION = 64;
constexpr std::size_t H_DURATION_SECONDS = 72;
constexpr std::size_t H_FULL_BUCKET_MS = 80;
constexpr std::size_t H_FOCUS_BUCKET_MS = 88;
constexpr std::size_t H_FOCUS_COUNT = 96;
constexpr std::size_t H_RING_SLOTS = 104;
constexpr std::size_t H_EXPECTED_FFT_SHIFT = 112;
constexpr std::size_t H_SAVE_FULLBAND_100MS = 120;
constexpr std::size_t H_PRODUCER_BASE = 128;
constexpr std::size_t H_CONSUMER_BASE = 256;
constexpr std::size_t H_DROP_BASE = 384;
constexpr std::size_t H_FOCUS_BIN_BASE = 512;

constexpr std::uint64_t S_READY = 1;
constexpr std::uint64_t S_RUNNING = 2;
constexpr std::uint64_t S_DRAINING = 3;
constexpr std::uint64_t S_COMPLETED = 4;
constexpr std::uint64_t S_FAILED = 5;

static_assert(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "Zarr output requires little endian");

std::uint64_t load_u64(const std::uint8_t* base, std::size_t offset,
                       int order = __ATOMIC_ACQUIRE) {
  return __atomic_load_n(reinterpret_cast<const std::uint64_t*>(base + offset), order);
}

void store_u64(std::uint8_t* base, std::size_t offset, std::uint64_t value,
               int order = __ATOMIC_RELEASE) {
  __atomic_store_n(reinterpret_cast<std::uint64_t*>(base + offset), value, order);
}

std::uint16_t read_u16(const std::uint8_t* p) {
  std::uint16_t value;
  std::memcpy(&value, p, sizeof(value));
  return value;
}

std::uint32_t read_u32(const std::uint8_t* p) {
  std::uint32_t value;
  std::memcpy(&value, p, sizeof(value));
  return value;
}

std::uint64_t read_u64(const std::uint8_t* p) {
  std::uint64_t value;
  std::memcpy(&value, p, sizeof(value));
  return value;
}

std::string cuda_error(cudaError_t status, const char* operation) {
  std::ostringstream out;
  out << operation << " failed: " << cudaGetErrorName(status) << ": "
      << cudaGetErrorString(status);
  return out.str();
}

void cuda_check(cudaError_t status, const char* operation) {
  if (status != cudaSuccess) {
    throw std::runtime_error(cuda_error(status, operation));
  }
}

std::string json_escape(const std::string& value) {
  std::ostringstream out;
  for (const unsigned char c : value) {
    switch (c) {
      case '"': out << "\\\""; break;
      case '\\': out << "\\\\"; break;
      case '\n': out << "\\n"; break;
      case '\r': out << "\\r"; break;
      case '\t': out << "\\t"; break;
      default:
        if (c < 0x20) {
          out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
              << static_cast<unsigned>(c) << std::dec;
        } else {
          out << c;
        }
    }
  }
  return out.str();
}

void write_all(int fd, const std::uint8_t* data, std::size_t bytes) {
  while (bytes != 0) {
    const ssize_t written = ::write(fd, data, bytes);
    if (written < 0) {
      if (errno == EINTR) continue;
      throw std::runtime_error("write failed: " + std::string(std::strerror(errno)));
    }
    data += static_cast<std::size_t>(written);
    bytes -= static_cast<std::size_t>(written);
  }
}

void atomic_write(const fs::path& path, const void* data, std::size_t bytes) {
  fs::create_directories(path.parent_path());
  const fs::path temp = path.string() + ".partial." + std::to_string(::getpid());
  const int fd = ::open(temp.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0640);
  if (fd < 0) {
    throw std::runtime_error("create " + temp.string() + " failed: " + std::strerror(errno));
  }
  try {
    write_all(fd, static_cast<const std::uint8_t*>(data), bytes);
    if (::fsync(fd) != 0) {
      throw std::runtime_error("fsync " + temp.string() + " failed: " + std::strerror(errno));
    }
    if (::close(fd) != 0) {
      throw std::runtime_error("close " + temp.string() + " failed: " + std::strerror(errno));
    }
    if (::rename(temp.c_str(), path.c_str()) != 0) {
      throw std::runtime_error("rename " + temp.string() + " failed: " + std::strerror(errno));
    }
  } catch (...) {
    ::close(fd);
    ::unlink(temp.c_str());
    throw;
  }
}

void atomic_write_text(const fs::path& path, const std::string& text) {
  atomic_write(path, text.data(), text.size());
}

std::string zarray(const std::string& shape, const std::string& chunks,
                   const std::string& dtype) {
  return "{\n  \"zarr_format\": 2,\n  \"shape\": " + shape +
         ",\n  \"chunks\": " + chunks + ",\n  \"dtype\": \"" + dtype +
         "\",\n  \"compressor\": null,\n  \"fill_value\": null,\n"
         "  \"order\": \"C\",\n  \"filters\": null\n}\n";
}

void create_array(const fs::path& root, const std::string& name,
                  const std::string& shape, const std::string& chunks,
                  const std::string& dtype, const std::string& attrs) {
  const fs::path dir = root / name;
  fs::create_directory(dir);
  atomic_write_text(dir / ".zarray", zarray(shape, chunks, dtype));
  atomic_write_text(dir / ".zattrs", attrs + "\n");
}

template <typename T>
void write_vector(const fs::path& path, const std::vector<T>& values) {
  atomic_write(path, values.data(), values.size() * sizeof(T));
}

struct Args {
  fs::path ring;
  fs::path output;
  fs::path request;
  fs::path oracle_raw;
  std::size_t oracle_spectra = 0;
  bool self_test = false;
  bool benchmark = false;
};

Args parse_args(int argc, char** argv) {
  Args args;
  for (int i = 1; i < argc; ++i) {
    const std::string option = argv[i];
    if (option == "--self-test") {
      args.self_test = true;
      continue;
    }
    if (option == "--benchmark") {
      args.benchmark = true;
      continue;
    }
    if (i + 1 >= argc) throw std::runtime_error("missing value for " + option);
    if (option == "--ring") args.ring = argv[++i];
    else if (option == "--output") args.output = argv[++i];
    else if (option == "--request") args.request = argv[++i];
    else if (option == "--oracle-raw") args.oracle_raw = argv[++i];
    else if (option == "--oracle-spectra") args.oracle_spectra = std::stoull(argv[++i]);
    else throw std::runtime_error("unknown option " + option);
  }
  if (!args.oracle_raw.empty() && (!args.self_test || args.oracle_spectra == 0 ||
                                  args.oracle_spectra > kRingSlots)) {
    throw std::runtime_error("--oracle-raw requires --self-test and 1..1024 --oracle-spectra");
  }
  if (args.self_test && args.benchmark) {
    throw std::runtime_error("--self-test and --benchmark are mutually exclusive");
  }
  if (!args.self_test && !args.benchmark &&
      (args.ring.empty() || args.output.empty() || args.request.empty())) {
    throw std::runtime_error("usage: t510_xcorr_cuda --ring PATH --output DIR --request JSON");
  }
  return args;
}

struct MappedRing {
  int fd = -1;
  std::uint8_t* host = nullptr;
  std::uint8_t* device = nullptr;
  std::size_t bytes = 0;
  bool cuda_registered = false;

  explicit MappedRing(const fs::path& path) {
    fd = ::open(path.c_str(), O_RDWR | O_CLOEXEC);
    if (fd < 0) throw std::runtime_error("open ring failed: " + std::string(std::strerror(errno)));
    struct stat status {};
    if (::fstat(fd, &status) != 0) throw std::runtime_error("fstat ring failed");
    bytes = static_cast<std::size_t>(status.st_size);
    const std::size_t expected = kHeaderBytes + kBlockCount * kRingSlots * kSlotBytes;
    if (bytes != expected) throw std::runtime_error("shared ring has unexpected size");
    void* mapping = ::mmap(nullptr, bytes, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (mapping == MAP_FAILED) throw std::runtime_error("mmap ring failed");
    host = static_cast<std::uint8_t*>(mapping);
  }

  void register_cuda() {
    cuda_check(cudaHostRegister(host, bytes, cudaHostRegisterMapped), "cudaHostRegister ring");
    cuda_registered = true;
    cuda_check(cudaHostGetDevicePointer(reinterpret_cast<void**>(&device), host, 0),
               "cudaHostGetDevicePointer ring");
  }

  ~MappedRing() {
    if (cuda_registered) cudaHostUnregister(host);
    if (host) ::munmap(host, bytes);
    if (fd >= 0) ::close(fd);
  }

  const std::uint8_t* slot(std::size_t block, std::uint64_t sequence) const {
    const std::size_t slot_index = static_cast<std::size_t>(sequence % kRingSlots);
    return host + kHeaderBytes + (block * kRingSlots + slot_index) * kSlotBytes;
  }
};

__constant__ std::uint8_t c_pair_left[kPairCount];
__constant__ std::uint8_t c_pair_right[kPairCount];

__global__ void accumulate_products(const std::int16_t* staged,
                                    std::uint32_t count,
                                    const std::int16_t* focus_map,
                                    std::uint32_t focus_count,
                                    double* auto_full,
                                    double2* cross_full,
                                    double* auto_focus,
                                    double2* cross_focus) {
  __shared__ std::int16_t
      tile[kCudaTimeTile * kCudaChannelsPerBlock * kAdcCount * 2];
  const std::uint32_t local_channel = threadIdx.x / kProductCount;
  const std::uint32_t product = threadIdx.x % kProductCount;
  const std::uint32_t global_bin =
      blockIdx.x * kCudaChannelsPerBlock + local_channel;
  constexpr std::uint32_t iq_per_channel = kAdcCount * 2;
  // IQ16 products fit signed 31 bits; a 512-frame batch fits comfortably in
  // int64 even for full-scale clipping. Integer accumulation is exact and
  // avoids the GB10's much lower FP64 multiply throughput. The batch sums are
  // below 2^41, so conversion to double and all 1 s totals remain exact.
  std::int64_t sum_re = 0;
  std::int64_t sum_im = 0;
  for (std::uint32_t tile_start = 0; tile_start < count;
       tile_start += kCudaTimeTile) {
    const std::uint32_t tile_count =
        min(static_cast<std::uint32_t>(kCudaTimeTile), count - tile_start);
    const std::uint32_t tile_values =
        tile_count * kCudaChannelsPerBlock * iq_per_channel;
    for (std::uint32_t index = threadIdx.x; index < tile_values;
         index += blockDim.x) {
      const std::uint32_t local_t =
          index / (kCudaChannelsPerBlock * iq_per_channel);
      const std::uint32_t within =
          index % (kCudaChannelsPerBlock * iq_per_channel);
      const std::uint32_t load_channel = within / iq_per_channel;
      const std::uint32_t iq = within % iq_per_channel;
      const std::uint32_t load_global =
          blockIdx.x * kCudaChannelsPerBlock + load_channel;
      const std::uint32_t load_block = load_global / kChannelsPerBlock;
      const std::uint32_t load_bin = load_global % kChannelsPerBlock;
      tile[index] =
          staged[(load_block * kMaxBatch + tile_start + local_t) *
                     kPayloadInt16 +
                 load_bin * iq_per_channel + iq];
    }
    __syncthreads();
    if (product < kAdcCount) {
      const std::uint32_t adc = product;
      for (std::uint32_t local_t = 0; local_t < tile_count; ++local_t) {
        const std::int16_t* iq =
            tile + (local_t * kCudaChannelsPerBlock + local_channel) *
                       iq_per_channel +
            adc * 2;
        const std::int32_t i = iq[0];
        const std::int32_t q = iq[1];
        sum_re += static_cast<std::int64_t>(i) * i +
                  static_cast<std::int64_t>(q) * q;
      }
    } else {
      const std::uint32_t pair = product - kAdcCount;
      const std::uint32_t left = c_pair_left[pair];
      const std::uint32_t right = c_pair_right[pair];
      for (std::uint32_t local_t = 0; local_t < tile_count; ++local_t) {
        const std::int16_t* values =
            tile + (local_t * kCudaChannelsPerBlock + local_channel) *
                       iq_per_channel;
        const std::int32_t ia = values[left * 2];
        const std::int32_t qa = values[left * 2 + 1];
        const std::int32_t ib = values[right * 2];
        const std::int32_t qb = values[right * 2 + 1];
        // Xa * conj(Xb): (Ia Ib + Qa Qb) + i(Qa Ib - Ia Qb).
        sum_re += static_cast<std::int64_t>(ia) * ib +
                  static_cast<std::int64_t>(qa) * qb;
        sum_im += static_cast<std::int64_t>(qa) * ib -
                  static_cast<std::int64_t>(ia) * qb;
      }
    }
    __syncthreads();
  }
  const std::int16_t focus = focus_map[global_bin];
  if (product < kAdcCount) {
    const std::uint32_t adc = product;
    const double batch_re = static_cast<double>(sum_re);
    auto_full[adc * kGlobalBins + global_bin] += batch_re;
    if (focus >= 0 && static_cast<std::uint32_t>(focus) < focus_count) {
      auto_focus[adc * focus_count + static_cast<std::uint32_t>(focus)] += batch_re;
    }
  } else {
    const std::uint32_t pair = product - kAdcCount;
    const double batch_re = static_cast<double>(sum_re);
    const double batch_im = static_cast<double>(sum_im);
    double2& full = cross_full[pair * kGlobalBins + global_bin];
    full.x += batch_re;
    full.y += batch_im;
    if (focus >= 0 && static_cast<std::uint32_t>(focus) < focus_count) {
      double2& selected =
          cross_focus[pair * focus_count + static_cast<std::uint32_t>(focus)];
      selected.x += batch_re;
      selected.y += batch_im;
    }
  }
}

void launch_accumulate_products(const std::int16_t* staged,
                                std::uint32_t count,
                                const std::int16_t* focus_map,
                                std::uint32_t focus_count,
                                double* auto_full,
                                double2* cross_full,
                                double* auto_focus,
                                double2* cross_focus) {
  constexpr std::uint32_t blocks =
      kGlobalBins / kCudaChannelsPerBlock;
  accumulate_products<<<blocks, kCudaThreads>>>(
      staged, count, focus_map, focus_count, auto_full, cross_full,
      auto_focus, cross_focus);
}

int run_benchmark() {
  cuda_check(cudaSetDevice(0), "benchmark cudaSetDevice");
  std::array<std::uint8_t, kPairCount> pair_left {};
  std::array<std::uint8_t, kPairCount> pair_right {};
  std::size_t pair_index = 0;
  for (std::uint8_t a = 0; a < kAdcCount; ++a) {
    for (std::uint8_t b = a + 1; b < kAdcCount; ++b) {
      pair_left[pair_index] = a;
      pair_right[pair_index] = b;
      ++pair_index;
    }
  }
  cuda_check(cudaMemcpyToSymbol(c_pair_left, pair_left.data(), pair_left.size()),
             "benchmark pair left");
  cuda_check(cudaMemcpyToSymbol(c_pair_right, pair_right.data(), pair_right.size()),
             "benchmark pair right");

  std::int16_t* d_staged = nullptr;
  std::int16_t* d_focus_map = nullptr;
  double* d_auto_full = nullptr;
  double2* d_cross_full = nullptr;
  double* d_auto_focus = nullptr;
  double2* d_cross_focus = nullptr;
  const std::size_t staged_bytes =
      kBlockCount * kMaxBatch * kPayloadBytes;
  cuda_check(cudaMalloc(&d_staged, staged_bytes), "benchmark staged");
  cuda_check(cudaMalloc(&d_focus_map, kGlobalBins * sizeof(std::int16_t)),
             "benchmark focus map");
  cuda_check(cudaMalloc(&d_auto_full, kAdcCount * kGlobalBins * sizeof(double)),
             "benchmark auto full");
  cuda_check(cudaMalloc(&d_cross_full, kPairCount * kGlobalBins * sizeof(double2)),
             "benchmark cross full");
  cuda_check(cudaMalloc(&d_auto_focus, kAdcCount * sizeof(double)),
             "benchmark auto focus");
  cuda_check(cudaMalloc(&d_cross_focus, kPairCount * sizeof(double2)),
             "benchmark cross focus");
  cuda_check(cudaMemset(d_staged, 0, staged_bytes), "benchmark clear staged");
  cuda_check(cudaMemset(d_focus_map, 0xff, kGlobalBins * sizeof(std::int16_t)),
             "benchmark clear focus map");
  cuda_check(cudaMemset(d_auto_full, 0, kAdcCount * kGlobalBins * sizeof(double)),
             "benchmark clear auto full");
  cuda_check(cudaMemset(d_cross_full, 0, kPairCount * kGlobalBins * sizeof(double2)),
             "benchmark clear cross full");

  constexpr std::size_t warmup = 4;
  constexpr std::size_t iterations = 100;
  for (std::size_t i = 0; i < warmup; ++i) {
    launch_accumulate_products(d_staged, kMaxBatch, d_focus_map, 1,
                               d_auto_full, d_cross_full, d_auto_focus,
                               d_cross_focus);
  }
  cuda_check(cudaDeviceSynchronize(), "benchmark warmup");
  cudaEvent_t begin = nullptr;
  cudaEvent_t end = nullptr;
  cuda_check(cudaEventCreate(&begin), "benchmark create begin event");
  cuda_check(cudaEventCreate(&end), "benchmark create end event");
  cuda_check(cudaEventRecord(begin), "benchmark record begin");
  for (std::size_t i = 0; i < iterations; ++i) {
    launch_accumulate_products(d_staged, kMaxBatch, d_focus_map, 1,
                               d_auto_full, d_cross_full, d_auto_focus,
                               d_cross_focus);
  }
  cuda_check(cudaEventRecord(end), "benchmark record end");
  cuda_check(cudaEventSynchronize(end), "benchmark synchronize end");
  float elapsed_ms = 0.0f;
  cuda_check(cudaEventElapsedTime(&elapsed_ms, begin, end),
             "benchmark elapsed time");
  const double spectra_per_second =
      static_cast<double>(iterations * kMaxBatch) * 1000.0 / elapsed_ms;
  const double realtime_factor = spectra_per_second / 78125.0;
  std::cout << "{\"ok\":" << (realtime_factor >= 1.5 ? "true" : "false")
            << ",\"kernel_spectra_per_second\":" << std::fixed
            << std::setprecision(3) << spectra_per_second
            << ",\"required_spectra_per_second\":78125.0"
            << ",\"kernel_realtime_factor\":" << realtime_factor
            << ",\"batch\":" << kMaxBatch
            << ",\"iterations\":" << iterations << "}\n";
  cudaEventDestroy(end);
  cudaEventDestroy(begin);
  cudaFree(d_cross_focus);
  cudaFree(d_auto_focus);
  cudaFree(d_cross_full);
  cudaFree(d_auto_full);
  cudaFree(d_focus_map);
  cudaFree(d_staged);
  if (realtime_factor < 1.5) {
    throw std::runtime_error("CUDA kernel benchmark has less than 1.5x realtime margin");
  }
  return 0;
}

void stage_payloads(const std::uint8_t* host_ring,
                    const std::array<std::uint64_t, kBlockCount>& consumers,
                    std::size_t count, std::int16_t* device_staged) {
  for (std::size_t block = 0; block < kBlockCount; ++block) {
    const std::size_t slot = static_cast<std::size_t>(consumers[block] % kRingSlots);
    const std::size_t first = std::min(count, kRingSlots - slot);
    const std::uint8_t* source = host_ring + kHeaderBytes +
        (block * kRingSlots + slot) * kSlotBytes + kSlotHeaderBytes;
    std::uint8_t* destination = reinterpret_cast<std::uint8_t*>(device_staged) +
        block * kMaxBatch * kPayloadBytes;
    cuda_check(cudaMemcpy2DAsync(destination, kPayloadBytes, source, kSlotBytes,
                                 kPayloadBytes, first, cudaMemcpyHostToDevice),
               "stage ring payload batch");
    const std::size_t remaining = count - first;
    if (remaining != 0) {
      source = host_ring + kHeaderBytes + block * kRingSlots * kSlotBytes +
          kSlotHeaderBytes;
      destination += first * kPayloadBytes;
      cuda_check(cudaMemcpy2DAsync(destination, kPayloadBytes, source, kSlotBytes,
                                   kPayloadBytes, remaining, cudaMemcpyHostToDevice),
                 "stage wrapped ring payload batch");
    }
  }
  cuda_check(cudaDeviceSynchronize(), "synchronize staged ring payload batch");
}

struct Identity {
  bool set = false;
  std::uint16_t fft_shift = 0;
  std::uint16_t scale_mode = 0;
  std::uint32_t scale_id = 0;
  std::uint16_t board_id = 0;
  std::uint16_t product_id = 0;
  std::uint32_t sample_rate_hz = 0;
  std::uint16_t pfb_taps = 0;
  std::uint64_t sync_generation = 0;
  std::uint64_t sync_observation_tag = 0;
};

Identity decode_identity(const std::uint8_t* slot) {
  Identity value;
  value.set = true;
  value.fft_shift = read_u16(slot + 28);
  value.scale_mode = read_u16(slot + 30);
  value.scale_id = read_u32(slot + 32);
  value.board_id = read_u16(slot + 36);
  value.product_id = read_u16(slot + 38);
  value.sample_rate_hz = read_u32(slot + 40);
  value.pfb_taps = read_u16(slot + 44);
  value.sync_generation = read_u64(slot + 48);
  value.sync_observation_tag = read_u64(slot + 56);
  return value;
}

bool same_identity(const Identity& a, const Identity& b) {
  return a.fft_shift == b.fft_shift && a.scale_mode == b.scale_mode &&
         a.scale_id == b.scale_id && a.board_id == b.board_id &&
         a.product_id == b.product_id && a.sample_rate_hz == b.sample_rate_hz &&
         a.pfb_taps == b.pfb_taps && a.sync_generation == b.sync_generation &&
         a.sync_observation_tag == b.sync_observation_tag;
}

class ZarrWriter {
 public:
  ZarrWriter(fs::path output, std::uint64_t duration_seconds,
             std::vector<std::uint16_t> focus_bins, std::uint64_t generation,
             bool save_fullband_100ms)
      : output_(std::move(output)), root_(output_ / "xcorr.zarr"),
        duration_(duration_seconds), focus_bins_(std::move(focus_bins)),
        save_fullband_100ms_(save_fullband_100ms),
        focus_auto_(10 * kAdcCount * focus_bins_.size()),
        focus_cross_(10 * kPairCount * focus_bins_.size()),
        focus_start_(10), focus_end_(10), focus_nvalid_(10 * kBlockCount) {
    if (fs::exists(root_)) throw std::runtime_error("xcorr.zarr already exists");
    fs::create_directory(root_);
    atomic_write_text(root_ / ".zgroup", "{\"zarr_format\":2}\n");
    write_root_attrs(false, generation);
    const std::string seconds = std::to_string(duration_);
    const std::string focus_rows = std::to_string(duration_ * 10);
    const std::string focus_count = std::to_string(focus_bins_.size());
    create_array(root_, "mean_auto_power_count2", "[" + seconds + ",8,4096]",
                 "[1,8,256]", "<f8",
                 "{\"unit\":\"F-engine IQ16 count^2\",\"meaning\":\"mean |X|^2\"}");
    create_array(root_, "mean_cross_visibility_count2",
                 "[" + seconds + ",28,4096]", "[1,28,256]", "<c16",
                 "{\"unit\":\"F-engine IQ16 count^2\",\"definition\":\"mean(Xa*conj(Xb))\"}");
    create_array(root_, "sample0_start", "[" + seconds + "]", "[1]", "<u8", "{}");
    create_array(root_, "sample0_end", "[" + seconds + "]", "[1]", "<u8", "{}");
    create_array(root_, "n_valid", "[" + seconds + ",16]", "[1,16]", "<u8", "{}");
    if (save_fullband_100ms_) {
      create_array(root_, "mean_auto_power_count2_100ms",
                   "[" + focus_rows + ",8,4096]", "[10,8,256]", "<f8",
                   "{\"unit\":\"F-engine IQ16 count^2\",\"meaning\":\"100 ms mean |X|^2\"}");
      create_array(root_, "mean_cross_visibility_count2_100ms",
                   "[" + focus_rows + ",28,4096]", "[10,28,256]", "<c16",
                   "{\"unit\":\"F-engine IQ16 count^2\",\"definition\":\"100 ms mean(Xa*conj(Xb))\"}");
      create_array(root_, "sample0_start_100ms", "[" + focus_rows + "]", "[10]", "<u8", "{}");
      create_array(root_, "sample0_end_100ms", "[" + focus_rows + "]", "[10]", "<u8", "{}");
      create_array(root_, "n_valid_100ms", "[" + focus_rows + ",16]", "[10,16]", "<u8", "{}");
    }
    create_array(root_, "focus_mean_auto_power_count2",
                 "[" + focus_rows + ",8," + focus_count + "]",
                 "[10,8," + focus_count + "]", "<f8",
                 "{\"unit\":\"F-engine IQ16 count^2\"}");
    create_array(root_, "focus_mean_cross_visibility_count2",
                 "[" + focus_rows + ",28," + focus_count + "]",
                 "[10,28," + focus_count + "]", "<c16",
                 "{\"definition\":\"mean(Xa*conj(Xb))\"}");
    create_array(root_, "focus_sample0_start", "[" + focus_rows + "]", "[10]", "<u8", "{}");
    create_array(root_, "focus_sample0_end", "[" + focus_rows + "]", "[10]", "<u8", "{}");
    create_array(root_, "focus_n_valid", "[" + focus_rows + ",16]", "[10,16]", "<u8", "{}");
    create_array(root_, "global_bin", "[4096]", "[4096]", "<u2", "{}");
    create_array(root_, "focus_global_bin", "[" + focus_count + "]",
                 "[" + focus_count + "]", "<u2", "{}");
    create_array(root_, "pair_index", "[28,2]", "[28,2]", "|u1",
                 "{\"order\":\"(0,1),(0,2),...,(6,7)\"}");
    std::vector<std::uint16_t> global(kGlobalBins);
    for (std::size_t i = 0; i < global.size(); ++i) global[i] = i;
    write_vector(root_ / "global_bin" / "0", global);
    write_vector(root_ / "focus_global_bin" / "0", focus_bins_);
    std::vector<std::uint8_t> pairs;
    for (std::uint8_t a = 0; a < kAdcCount; ++a) {
      for (std::uint8_t b = a + 1; b < kAdcCount; ++b) {
        pairs.push_back(a);
        pairs.push_back(b);
      }
    }
    write_vector(root_ / "pair_index" / "0.0", pairs);
    quality_.open(output_ / "quality_ledger.jsonl", std::ios::out | std::ios::app);
    if (!quality_) throw std::runtime_error("open quality_ledger.jsonl failed");
    if (save_fullband_100ms_) {
      quality_100ms_.open(output_ / "quality_ledger_100ms.jsonl", std::ios::out | std::ios::app);
      if (!quality_100ms_) throw std::runtime_error("open quality_ledger_100ms.jsonl failed");
    }
  }

  void add_focus(std::size_t focus_index, const std::vector<double>& auto_sum,
                 const std::vector<double2>& cross_sum, std::uint64_t n,
                 std::uint64_t sample_start, std::uint64_t sample_end) {
    const std::size_t slot = focus_index % 10;
    const std::size_t f = focus_bins_.size();
    for (std::size_t adc = 0; adc < kAdcCount; ++adc) {
      for (std::size_t bin = 0; bin < f; ++bin) {
        focus_auto_[(slot * kAdcCount + adc) * f + bin] =
            auto_sum[adc * f + bin] / static_cast<double>(n);
      }
    }
    for (std::size_t pair = 0; pair < kPairCount; ++pair) {
      for (std::size_t bin = 0; bin < f; ++bin) {
        double2 value = cross_sum[pair * f + bin];
        value.x /= static_cast<double>(n);
        value.y /= static_cast<double>(n);
        focus_cross_[(slot * kPairCount + pair) * f + bin] = value;
      }
    }
    focus_start_[slot] = sample_start;
    focus_end_[slot] = sample_end;
    for (std::size_t block = 0; block < kBlockCount; ++block) {
      focus_nvalid_[slot * kBlockCount + block] = n;
    }
  }

  void write_fullband_100ms_second(
      std::size_t second, const std::vector<struct Fullband100Job>& rows,
      const std::array<std::uint64_t, kBlockCount>& drops);

  void write_second(std::size_t second, const std::vector<double>& auto_sum,
                    const std::vector<double2>& cross_sum, std::uint64_t n,
                    std::uint64_t sample_start, std::uint64_t sample_end,
                    const std::array<std::uint64_t, kBlockCount>& drops) {
    std::vector<double> auto_mean(auto_sum.size());
    std::vector<double2> cross_mean(cross_sum.size());
    for (std::size_t i = 0; i < auto_sum.size(); ++i) {
      auto_mean[i] = auto_sum[i] / static_cast<double>(n);
    }
    for (std::size_t i = 0; i < cross_sum.size(); ++i) {
      cross_mean[i].x = cross_sum[i].x / static_cast<double>(n);
      cross_mean[i].y = cross_sum[i].y / static_cast<double>(n);
    }
    const std::string index = std::to_string(second);
    for (std::size_t block = 0; block < kBlockCount; ++block) {
      std::vector<double> auto_block(kAdcCount * kChannelsPerBlock);
      std::vector<double2> cross_block(kPairCount * kChannelsPerBlock);
      for (std::size_t adc = 0; adc < kAdcCount; ++adc) {
        std::copy_n(auto_mean.begin() + adc * kGlobalBins + block * kChannelsPerBlock,
                    kChannelsPerBlock,
                    auto_block.begin() + adc * kChannelsPerBlock);
      }
      for (std::size_t pair = 0; pair < kPairCount; ++pair) {
        std::copy_n(cross_mean.begin() + pair * kGlobalBins + block * kChannelsPerBlock,
                    kChannelsPerBlock,
                    cross_block.begin() + pair * kChannelsPerBlock);
      }
      const std::string suffix = ".0." + std::to_string(block);
      write_vector(root_ / "mean_auto_power_count2" / (index + suffix), auto_block);
      write_vector(root_ / "mean_cross_visibility_count2" / (index + suffix), cross_block);
    }
    atomic_write(root_ / "sample0_start" / index, &sample_start, sizeof(sample_start));
    atomic_write(root_ / "sample0_end" / index, &sample_end, sizeof(sample_end));
    std::array<std::uint64_t, kBlockCount> nvalid {};
    nvalid.fill(n);
    atomic_write(root_ / "n_valid" / (index + ".0"), nvalid.data(), sizeof(nvalid));
    write_vector(root_ / "focus_mean_auto_power_count2" / (index + ".0.0"), focus_auto_);
    write_vector(root_ / "focus_mean_cross_visibility_count2" / (index + ".0.0"), focus_cross_);
    write_vector(root_ / "focus_sample0_start" / index, focus_start_);
    write_vector(root_ / "focus_sample0_end" / index, focus_end_);
    write_vector(root_ / "focus_n_valid" / (index + ".0"), focus_nvalid_);
    quality_ << "{\"second\":" << second << ",\"sample0_start\":" << sample_start
             << ",\"sample0_end\":" << sample_end << ",\"n_valid\":[";
    for (std::size_t block = 0; block < kBlockCount; ++block) {
      if (block) quality_ << ',';
      quality_ << n;
    }
    quality_ << "],\"ring_drops\":[";
    for (std::size_t block = 0; block < kBlockCount; ++block) {
      if (block) quality_ << ',';
      quality_ << drops[block];
    }
    quality_ << "],\"complete\":true}\n";
    quality_.flush();
    if (!quality_) throw std::runtime_error("write quality ledger failed");
  }

  void complete(std::uint64_t generation) {
    write_root_attrs(true, generation);
    atomic_write_text(output_ / "sidecar_status.json",
                      "{\"status\":\"completed\",\"backend\":\"CUDA 13\","
                      "\"zarr\":\"xcorr.zarr\"}\n");
  }

 private:
  void write_root_attrs(bool complete, std::uint64_t generation) {
    std::ostringstream attrs;
    attrs << "{\n  \"schema\": \"t510.crosscorrelation.zarr."
          << (save_fullband_100ms_ ? "v2" : "v1") << "\",\n"
          << "  \"complete\": " << (complete ? "true" : "false") << ",\n"
          << "  \"generation\": " << generation << ",\n"
          << "  \"sample_rate_hz\": 320000000,\n"
          << "  \"fullband_bucket_ms\": 1000,\n"
          << "  \"save_fullband_100ms\": "
          << (save_fullband_100ms_ ? "true" : "false") << ",\n"
          << "  \"one_second_derivation\": \"effective-frame-weighted merge of ten 100 ms rows\",\n"
          << "  \"focus_bucket_ms\": 100,\n"
          << "  \"visibility_definition\": \"mean(Xa*conj(Xb))\",\n"
          << "  \"physical_interpretation\": \"independent_50ohm_instrument_false_correlation_floor\"\n}\n";
    atomic_write_text(root_ / ".zattrs", attrs.str());
  }

  fs::path output_;
  fs::path root_;
  std::uint64_t duration_;
  std::vector<std::uint16_t> focus_bins_;
  bool save_fullband_100ms_;
  std::vector<double> focus_auto_;
  std::vector<double2> focus_cross_;
  std::vector<std::uint64_t> focus_start_;
  std::vector<std::uint64_t> focus_end_;
  std::vector<std::uint64_t> focus_nvalid_;
  std::ofstream quality_;
  std::ofstream quality_100ms_;
};

struct FocusJob {
  std::vector<double> auto_sum;
  std::vector<double2> cross_sum;
  std::uint64_t n = 0;
  std::uint64_t sample_start = 0;
  std::uint64_t sample_end = 0;
};

struct Fullband100Job {
  std::vector<double> auto_sum;
  std::vector<double2> cross_sum;
  std::uint64_t n = 0;
  std::uint64_t sample_start = 0;
  std::uint64_t sample_end = 0;
};

void ZarrWriter::write_fullband_100ms_second(
    std::size_t second, const std::vector<Fullband100Job>& rows,
    const std::array<std::uint64_t, kBlockCount>& drops) {
  if (!save_fullband_100ms_) {
    if (!rows.empty()) throw std::runtime_error("unexpected full-band 100 ms rows");
    return;
  }
  if (rows.size() != 10) {
    throw std::runtime_error("full-band writer job does not contain ten 100 ms rows");
  }
  const std::string index = std::to_string(second);
  for (std::size_t block = 0; block < kBlockCount; ++block) {
    std::vector<double> auto_block(10 * kAdcCount * kChannelsPerBlock);
    std::vector<double2> cross_block(10 * kPairCount * kChannelsPerBlock);
    for (std::size_t row = 0; row < rows.size(); ++row) {
      const double divisor = static_cast<double>(rows[row].n);
      if (rows[row].n == 0) throw std::runtime_error("zero-length full-band 100 ms row");
      for (std::size_t adc = 0; adc < kAdcCount; ++adc) {
        const std::size_t source = adc * kGlobalBins + block * kChannelsPerBlock;
        const std::size_t target = (row * kAdcCount + adc) * kChannelsPerBlock;
        for (std::size_t bin = 0; bin < kChannelsPerBlock; ++bin) {
          auto_block[target + bin] = rows[row].auto_sum[source + bin] / divisor;
        }
      }
      for (std::size_t pair = 0; pair < kPairCount; ++pair) {
        const std::size_t source = pair * kGlobalBins + block * kChannelsPerBlock;
        const std::size_t target = (row * kPairCount + pair) * kChannelsPerBlock;
        for (std::size_t bin = 0; bin < kChannelsPerBlock; ++bin) {
          const double2 value = rows[row].cross_sum[source + bin];
          cross_block[target + bin] = make_double2(value.x / divisor, value.y / divisor);
        }
      }
    }
    const std::string suffix = ".0." + std::to_string(block);
    write_vector(root_ / "mean_auto_power_count2_100ms" / (index + suffix), auto_block);
    write_vector(root_ / "mean_cross_visibility_count2_100ms" / (index + suffix), cross_block);
  }
  std::array<std::uint64_t, 10> starts {};
  std::array<std::uint64_t, 10> ends {};
  std::array<std::uint64_t, 10 * kBlockCount> nvalid {};
  for (std::size_t row = 0; row < rows.size(); ++row) {
    starts[row] = rows[row].sample_start;
    ends[row] = rows[row].sample_end;
    for (std::size_t block = 0; block < kBlockCount; ++block) {
      nvalid[row * kBlockCount + block] = rows[row].n;
    }
    quality_100ms_ << "{\"index\":" << second * 10 + row
                   << ",\"sample0_start\":" << rows[row].sample_start
                   << ",\"sample0_end\":" << rows[row].sample_end
                   << ",\"n_valid\":" << rows[row].n << ",\"ring_drops\":[";
    for (std::size_t block = 0; block < kBlockCount; ++block) {
      if (block) quality_100ms_ << ',';
      quality_100ms_ << drops[block];
    }
    quality_100ms_ << "],\"complete\":true}\n";
  }
  atomic_write(root_ / "sample0_start_100ms" / index, starts.data(),
               starts.size() * sizeof(starts[0]));
  atomic_write(root_ / "sample0_end_100ms" / index, ends.data(),
               ends.size() * sizeof(ends[0]));
  atomic_write(root_ / "n_valid_100ms" / (index + ".0"), nvalid.data(),
               nvalid.size() * sizeof(nvalid[0]));
  quality_100ms_.flush();
  if (!quality_100ms_) throw std::runtime_error("write 100 ms quality ledger failed");
}

struct SecondJob {
  std::size_t second = 0;
  std::vector<double> auto_sum;
  std::vector<double2> cross_sum;
  std::uint64_t n = 0;
  std::uint64_t sample_start = 0;
  std::uint64_t sample_end = 0;
  std::array<std::uint64_t, kBlockCount> drops {};
  std::vector<FocusJob> focus;
  std::vector<Fullband100Job> fullband_100ms;
};

class AsyncWriter {
 public:
  explicit AsyncWriter(ZarrWriter& writer) : writer_(writer), worker_([this] { run(); }) {}

  AsyncWriter(const AsyncWriter&) = delete;
  AsyncWriter& operator=(const AsyncWriter&) = delete;

  ~AsyncWriter() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      stopping_ = true;
    }
    ready_.notify_all();
    if (worker_.joinable()) worker_.join();
  }

  void submit(SecondJob job) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!error_.empty()) throw std::runtime_error("Zarr writer failed: " + error_);
    // Four queued seconds bound memory and make sustained disk lag a fatal
    // observation error instead of an unbounded backlog.
    if (queue_.size() >= 4) {
      throw std::runtime_error("bounded Zarr writer queue is full");
    }
    queue_.push_back(std::move(job));
    ready_.notify_one();
  }

  void check() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!error_.empty()) throw std::runtime_error("Zarr writer failed: " + error_);
  }

  void finish() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      stopping_ = true;
    }
    ready_.notify_all();
    if (worker_.joinable()) worker_.join();
    check();
  }

 private:
  void run() noexcept {
    try {
      while (true) {
        SecondJob job;
        {
          std::unique_lock<std::mutex> lock(mutex_);
          ready_.wait(lock, [this] { return stopping_ || !queue_.empty(); });
          if (queue_.empty()) {
            if (stopping_) return;
            continue;
          }
          job = std::move(queue_.front());
          queue_.pop_front();
        }
        if (job.focus.size() != 10) {
          throw std::runtime_error("writer job does not contain ten 100 ms rows");
        }
        for (std::size_t row = 0; row < job.focus.size(); ++row) {
          const FocusJob& focus = job.focus[row];
          writer_.add_focus(job.second * 10 + row, focus.auto_sum, focus.cross_sum,
                            focus.n, focus.sample_start, focus.sample_end);
        }
        writer_.write_fullband_100ms_second(
            job.second, job.fullband_100ms, job.drops);
        if (job.fullband_100ms.empty()) {
          writer_.write_second(job.second, job.auto_sum, job.cross_sum, job.n,
                               job.sample_start, job.sample_end, job.drops);
        } else {
          // The public 1 s product is deliberately formed from the same ten
          // 100 ms integer sums and their valid-frame weights.  This freezes
          // the requested parent/child relationship instead of merely writing
          // two numerically similar accumulations.
          std::vector<double> merged_auto(job.auto_sum.size(), 0.0);
          std::vector<double2> merged_cross(job.cross_sum.size(), make_double2(0.0, 0.0));
          std::uint64_t merged_n = 0;
          for (const Fullband100Job& row : job.fullband_100ms) {
            if (row.auto_sum.size() != merged_auto.size() ||
                row.cross_sum.size() != merged_cross.size()) {
              throw std::runtime_error("full-band 100 ms merge shape mismatch");
            }
            merged_n += row.n;
            for (std::size_t i = 0; i < merged_auto.size(); ++i) {
              merged_auto[i] += row.auto_sum[i];
            }
            for (std::size_t i = 0; i < merged_cross.size(); ++i) {
              merged_cross[i].x += row.cross_sum[i].x;
              merged_cross[i].y += row.cross_sum[i].y;
            }
          }
          if (merged_n != job.n) {
            throw std::runtime_error("full-band 100 ms valid-frame merge mismatch");
          }
          writer_.write_second(job.second, merged_auto, merged_cross, merged_n,
                               job.sample_start, job.sample_end, job.drops);
        }
      }
    } catch (const std::exception& error) {
      std::lock_guard<std::mutex> lock(mutex_);
      error_ = error.what();
      stopping_ = true;
    }
  }

  ZarrWriter& writer_;
  std::mutex mutex_;
  std::condition_variable ready_;
  std::deque<SecondJob> queue_;
  std::string error_;
  bool stopping_ = false;
  std::thread worker_;
};

void write_failure(const fs::path& output, const std::string& error) {
  try {
    atomic_write_text(output / "sidecar_status.json",
                      "{\"status\":\"failed\",\"error\":\"" +
                          json_escape(error) + "\"}\n");
  } catch (...) {
  }
}

std::array<std::uint64_t, kBlockCount> ring_counters(const MappedRing& ring,
                                                     std::size_t base) {
  std::array<std::uint64_t, kBlockCount> values {};
  for (std::size_t block = 0; block < kBlockCount; ++block) {
    values[block] = load_u64(ring.host, base + block * 8);
  }
  return values;
}

void validate_sequence(std::size_t block, std::size_t batch_offset,
                       std::uint64_t consumer, std::uint64_t sample0,
                       std::uint64_t frame, std::uint32_t seq,
                       std::uint64_t expected_sample0,
                       std::array<std::uint64_t, kBlockCount>& previous_frame,
                       std::array<std::uint32_t, kBlockCount>& previous_seq,
                       std::array<bool, kBlockCount>& have_previous) {
  if (sample0 != expected_sample0) {
    throw std::runtime_error(
        "gap or reorder detected in sample0 at block " + std::to_string(block) +
        " batch_offset=" + std::to_string(batch_offset) +
        " consumer=" + std::to_string(consumer) +
        " expected=" + std::to_string(expected_sample0) +
        " actual=" + std::to_string(sample0) +
        " frame=" + std::to_string(frame) + " seq=" + std::to_string(seq));
  }
  if (have_previous[block] &&
      (frame != previous_frame[block] + kBlockCount ||
       seq != static_cast<std::uint32_t>(previous_seq[block] + kBlockCount))) {
    throw std::runtime_error("gap, duplicate, or reorder detected in frame sequence");
  }
  previous_frame[block] = frame;
  previous_seq[block] = seq;
  have_previous[block] = true;
}

void validate_batch(const MappedRing& ring,
                    const std::array<std::uint64_t, kBlockCount>& consumers,
                    std::uint64_t expected_sample0, std::size_t count,
                    Identity& identity,
                    std::array<std::uint64_t, kBlockCount>& previous_frame,
                    std::array<std::uint32_t, kBlockCount>& previous_seq,
                    std::array<bool, kBlockCount>& have_previous) {
  for (std::size_t t = 0; t < count; ++t) {
    std::uint64_t group_base = std::numeric_limits<std::uint64_t>::max();
    for (std::size_t block = 0; block < kBlockCount; ++block) {
      const std::uint8_t* slot = ring.slot(block, consumers[block] + t);
      const std::uint64_t sample0 = read_u64(slot);
      const std::uint64_t frame = read_u64(slot + 8);
      const std::uint32_t seq = read_u32(slot + 16);
      const std::uint32_t flags = read_u32(slot + 20);
      validate_sequence(block, t, consumers[block], sample0, frame, seq,
                        expected_sample0 + t * kSampleStep,
                        previous_frame, previous_seq, have_previous);
      if (read_u16(slot + 24) != block || read_u16(slot + 26) != kPayloadBytes) {
        throw std::runtime_error("shared ring slot identity is corrupt");
      }
      if ((flags & kPfbActive) == 0 || (flags & kFftOnly) != 0) {
        throw std::runtime_error("SPEC PFB status changed during cross-correlation");
      }
      if (frame % kBlockCount != block || seq % kBlockCount != block) {
        throw std::runtime_error("frame_id or seq_no is not block aligned");
      }
      const std::uint64_t this_group = frame - block;
      if (group_base == std::numeric_limits<std::uint64_t>::max()) group_base = this_group;
      if (this_group != group_base) throw std::runtime_error("sixteen SPEC blocks do not form one frame");
      const Identity current = decode_identity(slot);
      if (!identity.set) identity = current;
      if (!same_identity(identity, current)) {
        throw std::runtime_error("capture identity changed during cross-correlation");
      }
      if (current.product_id != 0xf101 || current.sample_rate_hz != kSampleRate ||
          current.pfb_taps != 8) {
        throw std::runtime_error("unexpected F-engine product identity");
      }
    }
  }
}

std::array<std::int16_t, 2> self_test_value(std::size_t adc, std::size_t bin,
                                           std::size_t time) {
  if (adc == 0) return {3, 4};
  if (adc == 1) return {5, 12};
  const std::int32_t base_i = static_cast<std::int32_t>((bin * 17 + time * 29) % 101) - 50;
  const std::int32_t base_q = static_cast<std::int32_t>((bin * 31 + time * 11) % 97) - 48;
  if (adc == 2 || adc == 3) {
    return {static_cast<std::int16_t>(base_i), static_cast<std::int16_t>(base_q)};
  }
  if (adc == 4) {
    return {static_cast<std::int16_t>(-base_q), static_cast<std::int16_t>(base_i)};
  }
  if (adc == 5) {
    const bool quarter_turn = (bin / 16) % 2 != 0;
    return quarter_turn
               ? std::array<std::int16_t, 2>{static_cast<std::int16_t>(-base_q),
                                             static_cast<std::int16_t>(base_i)}
               : std::array<std::int16_t, 2>{static_cast<std::int16_t>(base_i),
                                             static_cast<std::int16_t>(base_q)};
  }
  if (adc == 6) {
    return {static_cast<std::int16_t>(time % 2 ? 32767 : -32768),
            static_cast<std::int16_t>(time % 2 ? -32768 : 32767)};
  }
  const std::int32_t drift = static_cast<std::int32_t>(time) - 10;
  return {static_cast<std::int16_t>(base_i + drift),
          static_cast<std::int16_t>(base_q - drift)};
}

int run_self_test(const Args& args) {
  cuda_check(cudaSetDevice(0), "self-test cudaSetDevice");
  // The production sidecar must fail closed before the math kernel sees a
  // missing, duplicate, or reordered spectrum. Exercise that exact validator.
  {
    std::array<std::uint64_t, kBlockCount> previous_frame {};
    std::array<std::uint32_t, kBlockCount> previous_seq {};
    std::array<bool, kBlockCount> have_previous {};
    validate_sequence(0, 0, 0, 1000, 16, 16, 1000,
                      previous_frame, previous_seq, have_previous);
    validate_sequence(0, 1, 0, 1000 + kSampleStep, 32, 32,
                      1000 + kSampleStep, previous_frame, previous_seq, have_previous);
    bool missing_rejected = false;
    try {
      validate_sequence(1, 0, 0, 1000 + 2 * kSampleStep, 17, 17, 1000,
                        previous_frame, previous_seq, have_previous);
    } catch (const std::runtime_error&) {
      missing_rejected = true;
    }
    bool reorder_rejected = false;
    try {
      validate_sequence(0, 2, 0, 1000 + 2 * kSampleStep, 16, 16,
                        1000 + 2 * kSampleStep,
                        previous_frame, previous_seq, have_previous);
    } catch (const std::runtime_error&) {
      reorder_rejected = true;
    }
    if (!missing_rejected || !reorder_rejected) {
      throw std::runtime_error("missing/reordered packet fail-closed oracle failed");
    }
  }
  const std::size_t samples = args.oracle_raw.empty() ? 20 : args.oracle_spectra;
  const std::size_t ring_bytes = kHeaderBytes + kBlockCount * kRingSlots * kSlotBytes;
  std::uint8_t* host_ring = nullptr;
  cuda_check(cudaHostAlloc(reinterpret_cast<void**>(&host_ring), ring_bytes,
                           cudaHostAllocMapped),
             "self-test allocate mapped ring");
  std::uint8_t* device_ring = nullptr;
  cuda_check(cudaHostGetDevicePointer(reinterpret_cast<void**>(&device_ring), host_ring, 0),
             "self-test map ring");
  std::array<std::uint64_t, kBlockCount> consumers {};
  std::vector<std::int16_t> raw;
  if (!args.oracle_raw.empty()) {
    const std::size_t values = samples * kAdcCount * kGlobalBins * 2;
    raw.resize(values);
    std::ifstream input(args.oracle_raw, std::ios::binary);
    if (!input || !input.read(reinterpret_cast<char*>(raw.data()),
                              static_cast<std::streamsize>(values * sizeof(std::int16_t))) ||
        input.peek() != std::char_traits<char>::eof()) {
      throw std::runtime_error("oracle raw IQ16 file size/read mismatch");
    }
  }
  for (std::size_t block = 0; block < kBlockCount; ++block) {
    for (std::size_t time = 0; time < samples; ++time) {
      std::uint8_t* slot = host_ring + kHeaderBytes +
          (block * kRingSlots + time) * kSlotBytes;
      std::int16_t* payload = reinterpret_cast<std::int16_t*>(slot + kSlotHeaderBytes);
      for (std::size_t channel = 0; channel < kChannelsPerBlock; ++channel) {
        const std::size_t bin = block * kChannelsPerBlock + channel;
        for (std::size_t adc = 0; adc < kAdcCount; ++adc) {
          const auto value = args.oracle_raw.empty()
              ? self_test_value(adc, bin, time)
              : std::array<std::int16_t, 2>{
                    raw[((time * kAdcCount + adc) * kGlobalBins + bin) * 2],
                    raw[((time * kAdcCount + adc) * kGlobalBins + bin) * 2 + 1]};
          payload[(channel * kAdcCount + adc) * 2] = value[0];
          payload[(channel * kAdcCount + adc) * 2 + 1] = value[1];
        }
      }
    }
  }
  std::array<std::uint8_t, kPairCount> pair_left {};
  std::array<std::uint8_t, kPairCount> pair_right {};
  std::size_t pair = 0;
  for (std::uint8_t a = 0; a < kAdcCount; ++a) {
    for (std::uint8_t b = a + 1; b < kAdcCount; ++b) {
      pair_left[pair] = a;
      pair_right[pair] = b;
      ++pair;
    }
  }
  cuda_check(cudaMemcpyToSymbol(c_pair_left, pair_left.data(), pair_left.size()),
             "self-test pair left");
  cuda_check(cudaMemcpyToSymbol(c_pair_right, pair_right.data(), pair_right.size()),
             "self-test pair right");
  const std::array<std::uint16_t, 4> focus_bins {0, 17, 2048, 4095};
  std::vector<std::int16_t> focus_map(kGlobalBins, -1);
  for (std::size_t i = 0; i < focus_bins.size(); ++i) focus_map[focus_bins[i]] = i;
  std::uint64_t* d_consumers = nullptr;
  std::int16_t* d_focus_map = nullptr;
  double* d_auto_full = nullptr;
  double2* d_cross_full = nullptr;
  double* d_auto_focus = nullptr;
  double2* d_cross_focus = nullptr;
  std::int16_t* d_staged = nullptr;
  cuda_check(cudaMalloc(&d_consumers, sizeof(consumers)), "self-test consumers");
  cuda_check(cudaMalloc(&d_focus_map, kGlobalBins * sizeof(std::int16_t)), "self-test focus map");
  cuda_check(cudaMalloc(&d_auto_full, kAdcCount * kGlobalBins * sizeof(double)), "self-test auto");
  cuda_check(cudaMalloc(&d_cross_full, kPairCount * kGlobalBins * sizeof(double2)), "self-test cross");
  cuda_check(cudaMalloc(&d_auto_focus, kAdcCount * focus_bins.size() * sizeof(double)),
             "self-test focus auto");
  cuda_check(cudaMalloc(&d_cross_focus, kPairCount * focus_bins.size() * sizeof(double2)),
             "self-test focus cross");
  cuda_check(cudaMalloc(&d_staged, kBlockCount * kMaxBatch * kPayloadBytes),
             "self-test staged payloads");
  cuda_check(cudaMemcpy(d_focus_map, focus_map.data(), kGlobalBins * sizeof(std::int16_t),
                        cudaMemcpyHostToDevice), "self-test upload focus map");
  cuda_check(cudaMemset(d_auto_full, 0, kAdcCount * kGlobalBins * sizeof(double)),
             "self-test clear auto");
  cuda_check(cudaMemset(d_cross_full, 0, kPairCount * kGlobalBins * sizeof(double2)),
             "self-test clear cross");
  std::vector<double> merged_focus_auto(kAdcCount * focus_bins.size(), 0.0);
  std::vector<double2> merged_focus_cross(kPairCount * focus_bins.size(), make_double2(0.0, 0.0));
  for (std::size_t offset = 0; offset < samples;) {
    const std::size_t count = std::min<std::size_t>(2, samples - offset);
    consumers.fill(offset);
    cuda_check(cudaMemcpy(d_consumers, consumers.data(), sizeof(consumers), cudaMemcpyHostToDevice),
               "self-test upload consumers");
    cuda_check(cudaMemset(d_auto_focus, 0, kAdcCount * focus_bins.size() * sizeof(double)),
               "self-test clear focus auto");
    cuda_check(cudaMemset(d_cross_focus, 0, kPairCount * focus_bins.size() * sizeof(double2)),
               "self-test clear focus cross");
    stage_payloads(host_ring, consumers, count, d_staged);
    launch_accumulate_products(
        d_staged, static_cast<std::uint32_t>(count), d_focus_map,
        static_cast<std::uint32_t>(focus_bins.size()), d_auto_full,
        d_cross_full, d_auto_focus, d_cross_focus);
    cuda_check(cudaGetLastError(), "self-test launch kernel");
    std::vector<double> auto_focus(merged_focus_auto.size());
    std::vector<double2> cross_focus(merged_focus_cross.size());
    cuda_check(cudaMemcpy(auto_focus.data(), d_auto_focus, auto_focus.size() * sizeof(double),
                          cudaMemcpyDeviceToHost), "self-test copy focus auto");
    cuda_check(cudaMemcpy(cross_focus.data(), d_cross_focus,
                          cross_focus.size() * sizeof(double2), cudaMemcpyDeviceToHost),
               "self-test copy focus cross");
    for (std::size_t i = 0; i < auto_focus.size(); ++i) merged_focus_auto[i] += auto_focus[i];
    for (std::size_t i = 0; i < cross_focus.size(); ++i) {
      merged_focus_cross[i].x += cross_focus[i].x;
      merged_focus_cross[i].y += cross_focus[i].y;
    }
    offset += count;
  }
  std::vector<double> gpu_auto(kAdcCount * kGlobalBins);
  std::vector<double2> gpu_cross(kPairCount * kGlobalBins);
  cuda_check(cudaMemcpy(gpu_auto.data(), d_auto_full, gpu_auto.size() * sizeof(double),
                        cudaMemcpyDeviceToHost), "self-test copy auto");
  cuda_check(cudaMemcpy(gpu_cross.data(), d_cross_full, gpu_cross.size() * sizeof(double2),
                        cudaMemcpyDeviceToHost), "self-test copy cross");
  std::vector<double> cpu_auto(gpu_auto.size(), 0.0);
  std::vector<double2> cpu_cross(gpu_cross.size(), make_double2(0.0, 0.0));
  for (std::size_t bin = 0; bin < kGlobalBins; ++bin) {
    for (std::size_t time = 0; time < samples; ++time) {
      std::array<std::array<std::int16_t, 2>, kAdcCount> values {};
      for (std::size_t adc = 0; adc < kAdcCount; ++adc) {
        if (args.oracle_raw.empty()) {
          values[adc] = self_test_value(adc, bin, time);
        } else {
          values[adc] = {
              raw[((time * kAdcCount + adc) * kGlobalBins + bin) * 2],
              raw[((time * kAdcCount + adc) * kGlobalBins + bin) * 2 + 1]};
        }
        const double i = values[adc][0];
        const double q = values[adc][1];
        cpu_auto[adc * kGlobalBins + bin] += i * i + q * q;
      }
      for (std::size_t p = 0; p < kPairCount; ++p) {
        const auto a = values[pair_left[p]];
        const auto b = values[pair_right[p]];
        cpu_cross[p * kGlobalBins + bin].x +=
            static_cast<double>(a[0]) * b[0] + static_cast<double>(a[1]) * b[1];
        cpu_cross[p * kGlobalBins + bin].y +=
            static_cast<double>(a[1]) * b[0] - static_cast<double>(a[0]) * b[1];
      }
    }
  }
  for (std::size_t i = 0; i < gpu_auto.size(); ++i) {
    if (gpu_auto[i] != cpu_auto[i]) throw std::runtime_error("GPU auto differs from CPU integer oracle");
  }
  for (std::size_t i = 0; i < gpu_cross.size(); ++i) {
    if (gpu_cross[i].x != cpu_cross[i].x || gpu_cross[i].y != cpu_cross[i].y) {
      throw std::runtime_error("GPU complex multiply differs from CPU integer oracle");
    }
  }
  for (std::size_t adc = 0; adc < kAdcCount; ++adc) {
    for (std::size_t f = 0; f < focus_bins.size(); ++f) {
      if (merged_focus_auto[adc * focus_bins.size() + f] !=
          gpu_auto[adc * kGlobalBins + focus_bins[f]]) {
        throw std::runtime_error("100 ms focus auto merge differs from full result");
      }
    }
  }
  for (std::size_t p = 0; p < kPairCount; ++p) {
    for (std::size_t f = 0; f < focus_bins.size(); ++f) {
      const double2 merged = merged_focus_cross[p * focus_bins.size() + f];
      const double2 full = gpu_cross[p * kGlobalBins + focus_bins[f]];
      if (merged.x != full.x || merged.y != full.y) {
        throw std::runtime_error("100 ms focus cross merge differs from full result");
      }
    }
  }
  // The synthetic first pair has an exact negative imaginary component, pinning conj sign.
  if (args.oracle_raw.empty() &&
      (gpu_cross[0].x != 20.0 * 63.0 || gpu_cross[0].y != 20.0 * -16.0)) {
    throw std::runtime_error("Xa*conj(Xb) sign oracle failed");
  }
  cudaFree(d_cross_focus);
  cudaFree(d_staged);
  cudaFree(d_auto_focus);
  cudaFree(d_cross_full);
  cudaFree(d_auto_full);
  cudaFree(d_focus_map);
  cudaFree(d_consumers);
  cudaFreeHost(host_ring);
  std::cout << "{\"ok\":true,\"oracle\":\"CPU integer\",\"spectra\":"
            << samples << ",\"source\":\""
            << (args.oracle_raw.empty() ? "synthetic" : "captured SPEC PCAP IQ16") << "\","
               "\"cases\":[\"independent deterministic noise\",\"common noise\","
               "\"fixed phase\",\"known bin-dependent phase\",\"slow drift\","
               "\"IQ16 clipping\",\"missing packet rejected\","
               "\"reordered packet rejected\"],\"focus_merge\":true,"
               "\"visibility\":\"Xa*conj(Xb)\"}\n";
  return 0;
}

int run(const Args& args) {
  if (!fs::is_regular_file(args.request)) throw std::runtime_error("request.json is missing");
  if (!fs::is_directory(args.output)) throw std::runtime_error("output directory is missing");
  MappedRing ring(args.ring);
  if (load_u64(ring.host, H_MAGIC) != kRingMagic ||
      load_u64(ring.host, H_VERSION) != kRingVersion ||
      load_u64(ring.host, H_RING_SLOTS) != kRingSlots) {
    throw std::runtime_error("shared ring ABI mismatch");
  }
  const std::uint64_t duration = load_u64(ring.host, H_DURATION_SECONDS);
  const std::uint64_t generation = load_u64(ring.host, H_GENERATION);
  const std::uint64_t save_fullband_100ms_raw =
      load_u64(ring.host, H_SAVE_FULLBAND_100MS);
  if (save_fullband_100ms_raw > 1) {
    throw std::runtime_error("save_fullband_100ms shared-ring flag is invalid");
  }
  const bool save_fullband_100ms = save_fullband_100ms_raw != 0;
  const std::size_t focus_count = static_cast<std::size_t>(load_u64(ring.host, H_FOCUS_COUNT));
  if (duration == 0 || duration > 3600 || load_u64(ring.host, H_FULL_BUCKET_MS) != 1000 ||
      load_u64(ring.host, H_FOCUS_BUCKET_MS) != 100 || focus_count == 0 || focus_count > 32) {
    throw std::runtime_error("shared ring request contract is invalid");
  }
  std::vector<std::uint16_t> focus_bins(focus_count);
  std::vector<std::int16_t> focus_map(kGlobalBins, -1);
  for (std::size_t i = 0; i < focus_count; ++i) {
    const std::uint64_t bin = load_u64(ring.host, H_FOCUS_BIN_BASE + i * 8);
    if (bin >= kGlobalBins || focus_map[bin] != -1) throw std::runtime_error("invalid focus bins");
    focus_bins[i] = static_cast<std::uint16_t>(bin);
    focus_map[bin] = static_cast<std::int16_t>(i);
  }

  cuda_check(cudaSetDevice(0), "cudaSetDevice");
  cudaDeviceProp property {};
  cuda_check(cudaGetDeviceProperties(&property, 0), "cudaGetDeviceProperties");
  if (!property.canMapHostMemory) throw std::runtime_error("CUDA device cannot map the shared ring");
  ring.register_cuda();

  std::array<std::uint8_t, kPairCount> pair_left {};
  std::array<std::uint8_t, kPairCount> pair_right {};
  std::size_t pair_index = 0;
  for (std::uint8_t a = 0; a < kAdcCount; ++a) {
    for (std::uint8_t b = a + 1; b < kAdcCount; ++b) {
      pair_left[pair_index] = a;
      pair_right[pair_index] = b;
      ++pair_index;
    }
  }
  cuda_check(cudaMemcpyToSymbol(c_pair_left, pair_left.data(), pair_left.size()),
             "copy pair left table");
  cuda_check(cudaMemcpyToSymbol(c_pair_right, pair_right.data(), pair_right.size()),
             "copy pair right table");

  std::uint64_t* d_consumers = nullptr;
  std::int16_t* d_focus_map = nullptr;
  double* d_auto_full = nullptr;
  double2* d_cross_full = nullptr;
  double* d_auto_focus = nullptr;
  double2* d_cross_focus = nullptr;
  std::int16_t* d_staged = nullptr;
  cuda_check(cudaMalloc(&d_consumers, kBlockCount * sizeof(std::uint64_t)), "allocate consumers");
  cuda_check(cudaMalloc(&d_focus_map, kGlobalBins * sizeof(std::int16_t)), "allocate focus map");
  cuda_check(cudaMalloc(&d_auto_full, kAdcCount * kGlobalBins * sizeof(double)), "allocate auto full");
  cuda_check(cudaMalloc(&d_cross_full, kPairCount * kGlobalBins * sizeof(double2)), "allocate cross full");
  cuda_check(cudaMalloc(&d_auto_focus, kAdcCount * focus_count * sizeof(double)), "allocate auto focus");
  cuda_check(cudaMalloc(&d_cross_focus, kPairCount * focus_count * sizeof(double2)), "allocate cross focus");
  cuda_check(cudaMalloc(&d_staged, kBlockCount * kMaxBatch * kPayloadBytes),
             "allocate staged payloads");
  cuda_check(cudaMemcpy(d_focus_map, focus_map.data(), kGlobalBins * sizeof(std::int16_t),
                        cudaMemcpyHostToDevice), "upload focus map");
  cuda_check(cudaMemset(d_auto_full, 0, kAdcCount * kGlobalBins * sizeof(double)), "clear auto full");
  cuda_check(cudaMemset(d_cross_full, 0, kPairCount * kGlobalBins * sizeof(double2)), "clear cross full");
  cuda_check(cudaMemset(d_auto_focus, 0, kAdcCount * focus_count * sizeof(double)), "clear auto focus");
  cuda_check(cudaMemset(d_cross_focus, 0, kPairCount * focus_count * sizeof(double2)), "clear cross focus");

  ZarrWriter writer(args.output, duration, focus_bins, generation,
                    save_fullband_100ms);
  AsyncWriter async_writer(writer);
  store_u64(ring.host, H_STATE, S_READY);
  while (load_u64(ring.host, H_STATE) != S_RUNNING) {
    if (load_u64(ring.host, H_CANCEL) || load_u64(ring.host, H_FAILED)) {
      throw std::runtime_error("capture cancelled before the formal window");
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  const std::uint64_t start = load_u64(ring.host, H_START_SAMPLE0);
  const std::uint64_t end = load_u64(ring.host, H_END_SAMPLE0);
  if (end != start + duration * kSampleRate) throw std::runtime_error("formal sample window is invalid");

  std::array<std::uint64_t, kBlockCount> previous_frame {};
  std::array<std::uint32_t, kBlockCount> previous_seq {};
  std::array<bool, kBlockCount> have_previous {};
  Identity identity;
  const std::uint64_t expected_fft_shift = load_u64(ring.host, H_EXPECTED_FFT_SHIFT);
  std::vector<double> h_auto_full(kAdcCount * kGlobalBins);
  std::vector<double2> h_cross_full(kPairCount * kGlobalBins);
  std::vector<double> previous_auto_full(kAdcCount * kGlobalBins, 0.0);
  std::vector<double2> previous_cross_full(kPairCount * kGlobalBins,
                                           make_double2(0.0, 0.0));
  std::vector<double> h_auto_focus(kAdcCount * focus_count);
  std::vector<double2> h_cross_focus(kPairCount * focus_count);
  std::vector<FocusJob> focus_jobs;
  focus_jobs.reserve(10);
  std::vector<Fullband100Job> fullband_100ms_jobs;
  fullband_100ms_jobs.reserve(10);
  std::uint64_t current = start;
  std::uint64_t focus_n = 0;
  std::uint64_t second_n = 0;
  const std::size_t focus_total = static_cast<std::size_t>(duration * 10);

  for (std::size_t focus_index_value = 0; focus_index_value < focus_total;) {
    async_writer.check();
    if (load_u64(ring.host, H_CANCEL) || load_u64(ring.host, H_FAILED)) {
      throw std::runtime_error("capture cancelled or producer reported a fatal error");
    }
    const auto consumers = ring_counters(ring, H_CONSUMER_BASE);
    const auto producers = ring_counters(ring, H_PRODUCER_BASE);
    std::uint64_t available = std::numeric_limits<std::uint64_t>::max();
    for (std::size_t block = 0; block < kBlockCount; ++block) {
      if (producers[block] < consumers[block]) throw std::runtime_error("ring counters regressed");
      available = std::min(available, producers[block] - consumers[block]);
      if (load_u64(ring.host, H_DROP_BASE + block * 8) != 0) {
        throw std::runtime_error("producer recorded a ring drop");
      }
    }
    if (available == 0) {
      std::this_thread::sleep_for(std::chrono::microseconds(50));
      continue;
    }
    const std::uint64_t focus_end = start + (focus_index_value + 1) * kFocusTicks;
    const std::uint64_t frames_to_boundary =
        (focus_end - current + kSampleStep - 1) / kSampleStep;
    const std::size_t count = static_cast<std::size_t>(std::min<std::uint64_t>(
        {available, frames_to_boundary, kMaxBatch}));
    validate_batch(ring, consumers, current, count, identity, previous_frame,
                   previous_seq, have_previous);
    if (expected_fft_shift != std::numeric_limits<std::uint64_t>::max() &&
        identity.fft_shift != expected_fft_shift) {
      throw std::runtime_error("fft_shift does not match the frozen request");
    }
    stage_payloads(ring.host, consumers, count, d_staged);
    // The GPU now owns an immutable device copy.  Release the bounded host
    // slots immediately so producer headroom covers compute, not DMA+compute.
    for (std::size_t block = 0; block < kBlockCount; ++block) {
      store_u64(ring.host, H_CONSUMER_BASE + block * 8, consumers[block] + count);
    }
    launch_accumulate_products(
        d_staged, static_cast<std::uint32_t>(count), d_focus_map,
        static_cast<std::uint32_t>(focus_count), d_auto_full, d_cross_full,
        d_auto_focus, d_cross_focus);
    cuda_check(cudaGetLastError(), "launch cross-correlation kernel");
    cuda_check(cudaDeviceSynchronize(), "synchronize cross-correlation kernel");
    current += count * kSampleStep;
    focus_n += count;
    second_n += count;
    if (current >= focus_end) {
      if (current != focus_end && current - focus_end >= kSampleStep) {
        throw std::runtime_error("focus bucket boundary arithmetic failed");
      }
      cuda_check(cudaMemcpy(h_auto_focus.data(), d_auto_focus,
                            h_auto_focus.size() * sizeof(double), cudaMemcpyDeviceToHost),
                 "download focus auto");
      cuda_check(cudaMemcpy(h_cross_focus.data(), d_cross_focus,
                            h_cross_focus.size() * sizeof(double2), cudaMemcpyDeviceToHost),
                 "download focus cross");
      const std::uint64_t focus_start_sample = start + focus_index_value * kFocusTicks;
      focus_jobs.push_back(FocusJob{h_auto_focus, h_cross_focus, focus_n,
                                    focus_start_sample, focus_end});
      if (save_fullband_100ms) {
        cuda_check(cudaMemcpy(h_auto_full.data(), d_auto_full,
                              h_auto_full.size() * sizeof(double), cudaMemcpyDeviceToHost),
                   "download cumulative 100 ms fullband auto");
        cuda_check(cudaMemcpy(h_cross_full.data(), d_cross_full,
                              h_cross_full.size() * sizeof(double2), cudaMemcpyDeviceToHost),
                   "download cumulative 100 ms fullband cross");
        Fullband100Job row;
        row.auto_sum.resize(h_auto_full.size());
        row.cross_sum.resize(h_cross_full.size());
        for (std::size_t i = 0; i < h_auto_full.size(); ++i) {
          row.auto_sum[i] = h_auto_full[i] - previous_auto_full[i];
        }
        for (std::size_t i = 0; i < h_cross_full.size(); ++i) {
          row.cross_sum[i] = make_double2(
              h_cross_full[i].x - previous_cross_full[i].x,
              h_cross_full[i].y - previous_cross_full[i].y);
        }
        previous_auto_full = h_auto_full;
        previous_cross_full = h_cross_full;
        row.n = focus_n;
        row.sample_start = focus_start_sample;
        row.sample_end = focus_end;
        fullband_100ms_jobs.push_back(std::move(row));
      }
      cuda_check(cudaMemset(d_auto_focus, 0, kAdcCount * focus_count * sizeof(double)),
                 "reset focus auto");
      cuda_check(cudaMemset(d_cross_focus, 0, kPairCount * focus_count * sizeof(double2)),
                 "reset focus cross");
      focus_n = 0;
      ++focus_index_value;
      if (focus_index_value % 10 == 0) {
        const std::size_t second = focus_index_value / 10 - 1;
        if (!save_fullband_100ms) {
          cuda_check(cudaMemcpy(h_auto_full.data(), d_auto_full,
                                h_auto_full.size() * sizeof(double), cudaMemcpyDeviceToHost),
                     "download fullband auto");
          cuda_check(cudaMemcpy(h_cross_full.data(), d_cross_full,
                                h_cross_full.size() * sizeof(double2), cudaMemcpyDeviceToHost),
                     "download fullband cross");
        }
        const auto drops = ring_counters(ring, H_DROP_BASE);
        SecondJob job;
        job.second = second;
        job.auto_sum = h_auto_full;
        job.cross_sum = h_cross_full;
        job.n = second_n;
        job.sample_start = start + second * kSampleRate;
        job.sample_end = start + (second + 1) * kSampleRate;
        job.drops = drops;
        job.focus = std::move(focus_jobs);
        job.fullband_100ms = std::move(fullband_100ms_jobs);
        async_writer.submit(std::move(job));
        focus_jobs.clear();
        focus_jobs.reserve(10);
        fullband_100ms_jobs.clear();
        fullband_100ms_jobs.reserve(10);
        cuda_check(cudaMemset(d_auto_full, 0, kAdcCount * kGlobalBins * sizeof(double)),
                   "reset fullband auto");
        cuda_check(cudaMemset(d_cross_full, 0, kPairCount * kGlobalBins * sizeof(double2)),
                   "reset fullband cross");
        std::fill(previous_auto_full.begin(), previous_auto_full.end(), 0.0);
        std::fill(previous_cross_full.begin(), previous_cross_full.end(), make_double2(0.0, 0.0));
        second_n = 0;
      }
    }
  }
  if (current != end || second_n != 0 || focus_n != 0) {
    throw std::runtime_error("capture ended at the wrong formal sample boundary");
  }
  store_u64(ring.host, H_STATE, S_DRAINING);
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
  while (load_u64(ring.host, H_COMPLETED_MASK) != 0xffff) {
    if (load_u64(ring.host, H_CANCEL) || load_u64(ring.host, H_FAILED)) {
      throw std::runtime_error("producer failed while sealing capture");
    }
    if (std::chrono::steady_clock::now() >= deadline) {
      throw std::runtime_error("all sixteen blocks did not cross the formal end boundary");
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  for (std::size_t block = 0; block < kBlockCount; ++block) {
    if (load_u64(ring.host, H_DROP_BASE + block * 8) != 0) {
      throw std::runtime_error("nonzero ring drop while sealing capture");
    }
  }
  async_writer.finish();
  writer.complete(generation);
  store_u64(ring.host, H_STATE, S_COMPLETED);
  cudaFree(d_cross_focus);
  cudaFree(d_staged);
  cudaFree(d_auto_focus);
  cudaFree(d_cross_full);
  cudaFree(d_auto_full);
  cudaFree(d_focus_map);
  cudaFree(d_consumers);
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  Args args;
  std::uint8_t* ring_header = nullptr;
  std::size_t ring_bytes = 0;
  int ring_fd = -1;
  try {
    args = parse_args(argc, argv);
    if (args.self_test) return run_self_test(args);
    if (args.benchmark) return run_benchmark();
    return run(args);
  } catch (const std::exception& error) {
    std::cerr << "t510_xcorr_cuda: " << error.what() << '\n';
    if (!args.output.empty()) write_failure(args.output, error.what());
    if (!args.ring.empty()) {
      ring_fd = ::open(args.ring.c_str(), O_RDWR | O_CLOEXEC);
      if (ring_fd >= 0) {
        struct stat status {};
        if (::fstat(ring_fd, &status) == 0 && status.st_size >= static_cast<off_t>(kHeaderBytes)) {
          ring_bytes = static_cast<std::size_t>(status.st_size);
          void* mapped = ::mmap(nullptr, ring_bytes, PROT_READ | PROT_WRITE, MAP_SHARED, ring_fd, 0);
          if (mapped != MAP_FAILED) {
            ring_header = static_cast<std::uint8_t*>(mapped);
            store_u64(ring_header, H_FAILED, 1);
            store_u64(ring_header, H_CANCEL, 1);
            store_u64(ring_header, H_STATE, S_FAILED);
            ::munmap(ring_header, ring_bytes);
          }
        }
        ::close(ring_fd);
      }
    }
    return 1;
  }
}
