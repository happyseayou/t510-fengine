# Generated RFDC/BD IP constraints can be scoped to cells that are only present
# inside OOC IP netlists. During top-level blackbox synthesis Vivado emits
# Designutils 20-1275 for those files even though implementation re-links the IP
# checkpoints and timing remains checked post-route.
set_msg_config -id {Designutils 20-1275} -new_severity {WARNING}
