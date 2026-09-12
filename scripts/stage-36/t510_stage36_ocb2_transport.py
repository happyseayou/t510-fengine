#!/usr/bin/env python3
"""GB10-to-board transport with pinned host key and public lab credentials."""
import json
import shlex
import os
from pathlib import Path
import sys
import paramiko

client = paramiko.SSHClient()
client.load_host_keys(str(Path(__file__).with_name('board-known-hosts')))
client.connect('192.168.100.117', username='xilinx', password=os.environ.get('PYNQ_SUDO_PASSWORD','xilinx'),
               look_for_keys=False, allow_agent=False, timeout=10)
action = sys.argv[1]
if action not in ('probe','snapshot','A','B','release'):
    raise ValueError('invalid OCB2 action')
helper = os.environ.get('T510_INIT_HELPER', '/home/xilinx/t510-stage36-ocb2-20260912/t510_stage36_ocb2_probe.py')
command = 'sudo -S -p "" env XILINX_XRT=/usr PYTHONPATH=/opt/t510-agent/current /usr/local/share/pynq-venv/bin/python3 ' + shlex.quote(helper) + ' ' + action
stdin, stdout, stderr = client.exec_command(command, timeout=170)
stdin.write(os.environ.get('PYNQ_SUDO_PASSWORD','xilinx')+'\n'); stdin.flush(); stdin.channel.shutdown_write()
out, err = stdout.read().decode(), stderr.read().decode()
code = stdout.channel.recv_exit_status()
client.close()
print(out, end='')
print(err, file=sys.stderr, end='')
sys.exit(code)
