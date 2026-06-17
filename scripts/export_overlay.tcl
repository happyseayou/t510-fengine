set script_path [info script]
if {$script_path eq ""} {
    set origin_dir [pwd]
} else {
    set origin_dir [file dirname [file normalize $script_path]]
}
set repo_root [file normalize [file join $origin_dir ".."]]
if {![file exists [file join $repo_root rtl pl_mts_sync_clk.v]]} {
    set pwd_root [file normalize [pwd]]
    if {[file exists [file join $pwd_root rtl pl_mts_sync_clk.v]]} {
        set repo_root $pwd_root
    } elseif {[file exists [file join $pwd_root demo-ant rtl pl_mts_sync_clk.v]]} {
        set repo_root [file normalize [file join $pwd_root demo-ant]]
    } else {
        error "Unable to resolve repo root from script_path='$script_path' pwd='[pwd]'"
    }
}
set out_dir [file join $repo_root overlay]
set bd_name t510_rfdc_bd
set overlay_name t510_fengine

file mkdir $out_dir

if {[catch {current_project} project_name] != 0 || $project_name eq ""} {
    error "No Vivado project is open. Open demo-ant.xpr before sourcing export_overlay.tcl."
}

set bd_files [get_files -quiet "*/${bd_name}.bd"]
if {[llength $bd_files] == 0} {
    set fallback_bd [file join $repo_root "demo-ant.srcs" "sources_1" "bd" $bd_name "${bd_name}.bd"]
    if {[file exists $fallback_bd]} {
        add_files -norecurse -fileset sources_1 $fallback_bd
        set bd_files [list $fallback_bd]
    }
}
if {[llength $bd_files] == 0} {
    error "Could not find ${bd_name}.bd in the current project."
}
set bd_file [lindex $bd_files 0]

open_bd_design $bd_file
validate_bd_design

set bd_tcl_out [file join $out_dir "${overlay_name}.tcl"]
write_bd_tcl -force $bd_tcl_out

set hwh_candidates [list \
    [file join $repo_root "demo-ant.gen" "sources_1" "bd" $bd_name "hw_handoff" "${bd_name}.hwh"] \
]
set hwh_src ""
foreach candidate $hwh_candidates {
    if {[file exists $candidate]} {
        set hwh_src $candidate
        break
    }
}
if {$hwh_src eq ""} {
    puts "INFO: HWH not found; generating BD targets."
    generate_target all [get_files $bd_file]
    foreach candidate $hwh_candidates {
        if {[file exists $candidate]} {
            set hwh_src $candidate
            break
        }
    }
}
if {$hwh_src eq ""} {
    error "Could not find generated ${bd_name}.hwh after generate_target."
}
set hwh_out [file join $out_dir "${overlay_name}.hwh"]
file copy -force $hwh_src $hwh_out

set top_name [get_property TOP [get_filesets sources_1]]
set bit_candidates [list \
    [file join $repo_root "demo-ant.runs" "impl_1" "${top_name}.bit"] \
    [file join $repo_root "demo-ant.runs" "impl_1" "${overlay_name}.bit"] \
]
set bit_src ""
foreach candidate $bit_candidates {
    if {[file exists $candidate]} {
        set bit_src $candidate
        break
    }
}
set bit_out [file join $out_dir "${overlay_name}.bit"]
if {$bit_src ne ""} {
    if {[file normalize $bit_src] ne [file normalize $bit_out]} {
        file copy -force $bit_src $bit_out
    }
} else {
    set bit_out ""
    puts "WARN: bitstream not found under demo-ant.runs/impl_1; manifest will not point at an existing stale ${overlay_name}.bit."
}

set ltx_candidates [glob -nocomplain [file join $repo_root "demo-ant.runs" "impl_1" "*.ltx"]]
set ltx_out ""
if {[llength $ltx_candidates] != 0} {
    set ltx_out [file join $out_dir "${overlay_name}.ltx"]
    file copy -force [lindex $ltx_candidates 0] $ltx_out
}

set manifest [file join $out_dir "${overlay_name}.manifest.txt"]
set fh [open $manifest w]
puts $fh "project=$project_name"
puts $fh "part=[get_property PART [current_project]]"
puts $fh "top=$top_name"
puts $fh "bd=$bd_file"
puts $fh "bd_tcl=$bd_tcl_out"
puts $fh "hwh=$hwh_out"
puts $fh "bit=$bit_out"
puts $fh "ltx=$ltx_out"
close $fh

puts "INFO: exported overlay metadata to $out_dir"
