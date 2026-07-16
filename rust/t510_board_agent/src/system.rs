use serde::Serialize;
use std::ffi::CStr;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};
use std::path::Path;

#[derive(Clone, Debug, Serialize)]
pub struct NetworkAddress {
    pub interface: String,
    pub address: String,
    pub management: bool,
}

#[derive(Clone, Debug, Serialize)]
pub struct MemoryInfo {
    pub total_kib: u64,
    pub available_kib: u64,
}

pub fn read_trimmed(path: impl AsRef<Path>) -> Result<String, String> {
    std::fs::read_to_string(path.as_ref())
        .map(|value| value.trim().to_string())
        .map_err(|error| format!("cannot read {}: {error}", path.as_ref().display()))
}

pub fn interface_mac(interface: &str) -> Result<String, String> {
    read_trimmed(format!("/sys/class/net/{interface}/address"))
        .map(|value| value.to_ascii_lowercase())
}

pub fn device_uid(mac: &str) -> String {
    format!("t510-psmac-{}", mac.replace(':', "").to_ascii_lowercase())
}

pub fn memory_info() -> Result<MemoryInfo, String> {
    let content = read_trimmed("/proc/meminfo")?;
    let mut total = None;
    let mut available = None;
    for line in content.lines() {
        let mut parts = line.split_whitespace();
        match parts.next() {
            Some("MemTotal:") => total = parts.next().and_then(|value| value.parse().ok()),
            Some("MemAvailable:") => available = parts.next().and_then(|value| value.parse().ok()),
            _ => {}
        }
    }
    Ok(MemoryInfo {
        total_kib: total.ok_or("MemTotal is missing from /proc/meminfo")?,
        available_kib: available.ok_or("MemAvailable is missing from /proc/meminfo")?,
    })
}

pub fn network_addresses(management_interface: &str) -> Result<Vec<NetworkAddress>, String> {
    let mut head: *mut libc::ifaddrs = std::ptr::null_mut();
    if unsafe { libc::getifaddrs(&mut head) } != 0 {
        return Err(format!(
            "getifaddrs failed: {}",
            std::io::Error::last_os_error()
        ));
    }
    let mut result = Vec::new();
    let mut current = head;
    while !current.is_null() {
        let item = unsafe { &*current };
        if !item.ifa_addr.is_null() {
            let name = unsafe { CStr::from_ptr(item.ifa_name) }
                .to_string_lossy()
                .into_owned();
            let family = unsafe { (*item.ifa_addr).sa_family as i32 };
            let address = match family {
                libc::AF_INET => {
                    let sockaddr = unsafe { &*(item.ifa_addr as *const libc::sockaddr_in) };
                    let octets = sockaddr.sin_addr.s_addr.to_ne_bytes();
                    Some(IpAddr::V4(Ipv4Addr::new(
                        octets[0], octets[1], octets[2], octets[3],
                    )))
                }
                libc::AF_INET6 => {
                    let sockaddr = unsafe { &*(item.ifa_addr as *const libc::sockaddr_in6) };
                    Some(IpAddr::V6(Ipv6Addr::from(sockaddr.sin6_addr.s6_addr)))
                }
                _ => None,
            };
            if let Some(address) = address {
                if !address.is_loopback() {
                    let management = name == management_interface
                        || name
                            .strip_prefix(management_interface)
                            .is_some_and(|suffix| suffix.starts_with(':'));
                    result.push(NetworkAddress {
                        management,
                        interface: name,
                        address: address.to_string(),
                    });
                }
            }
        }
        current = item.ifa_next;
    }
    unsafe { libc::freeifaddrs(head) };
    result.sort_by(|left, right| {
        left.interface
            .cmp(&right.interface)
            .then(left.address.cmp(&right.address))
    });
    result
        .dedup_by(|left, right| left.interface == right.interface && left.address == right.address);
    Ok(result)
}
