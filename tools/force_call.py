import ctypes as C, ctypes.wintypes as W, struct, subprocess, sys, time

k32 = C.WinDLL('kernel32', use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
k32.VirtualAllocEx.restype = C.c_void_p
k32.VirtualAllocEx.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, W.DWORD, W.DWORD]
k32.WriteProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
k32.CreateRemoteThread.restype = W.HANDLE
k32.CreateRemoteThread.argtypes = [W.HANDLE, C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, W.DWORD, C.c_void_p]
k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]

def find_pid():
    pid = 0
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq codol1649370-offline.exe', '/FO', 'CSV'], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = [x.strip('"') for x in line.split('","')]
        if len(p) > 1 and p[1].isdigit():
            pid = int(p[1])
    return pid

target = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x8018B0
pid = find_pid()
print('pid', pid, 'target', hex(target))
if not pid:
    raise SystemExit
h = k32.OpenProcess(0x1F0FFF, False, pid)
if not h:
    raise SystemExit('OpenProcess failed')
# shellcode: mov eax, imm32 ; call eax ; ret
shellcode = b'\xB8' + struct.pack('<I', target) + b'\xFF\xD0\xC3'
mem = k32.VirtualAllocEx(h, None, 0x1000, 0x3000, 0x40)
if not mem:
    raise SystemExit('VirtualAllocEx failed')
written = C.c_size_t()
ok = k32.WriteProcessMemory(h, mem, C.create_string_buffer(shellcode, len(shellcode)), len(shellcode), C.byref(written))
print('alloc', hex(mem), 'write', bool(ok), 'bytes', written.value)
thread = k32.CreateRemoteThread(h, None, 0, mem, None, 0, None)
print('thread', hex(thread) if thread else None)
if thread:
    k32.WaitForSingleObject(thread, 5000)
    print('thread finished')
