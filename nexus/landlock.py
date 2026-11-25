"""Linux kernel enforcement for the web process's filesystem writes."""

import ctypes
import os
import platform
import struct

LIBC = ctypes.CDLL(None, use_errno=True)
LIBC.syscall.restype = ctypes.c_long

CREATE_RULESET = 444
ADD_RULE = 445
RESTRICT_SELF = 446
CREATE_VERSION = 1
RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38

WRITE_FILE = 1 << 1
REMOVE_DIR, REMOVE_FILE = 1 << 4, 1 << 5
MAKE_CHAR, MAKE_DIR, MAKE_REG = 1 << 6, 1 << 7, 1 << 8
MAKE_SOCK, MAKE_FIFO, MAKE_BLOCK, MAKE_SYM = 1 << 9, 1 << 10, 1 << 11, 1 << 12
REFER, TRUNCATE = 1 << 13, 1 << 14

WRITABLE_TREE = WRITE_FILE | REMOVE_DIR | REMOVE_FILE | MAKE_DIR | MAKE_REG | REFER | TRUNCATE
HANDLED = WRITABLE_TREE | MAKE_CHAR | MAKE_SOCK | MAKE_FIFO | MAKE_BLOCK | MAKE_SYM


def syscall(number, *arguments):
    result = LIBC.syscall(ctypes.c_long(number), *arguments)
    if result < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return result


def restrict_writes(state_dir, workspace_fds):
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise RuntimeError("Nexus requires Linux x86-64 or ARM64")
    try:
        if syscall(CREATE_RULESET, None, ctypes.c_size_t(0), CREATE_VERSION) < 3:
            raise RuntimeError("Nexus requires Landlock ABI 3 or newer (Linux 6.2+)")
        config = ctypes.c_uint64(HANDLED)
        rule = syscall(
            CREATE_RULESET, ctypes.byref(config), ctypes.c_size_t(ctypes.sizeof(config)), 0
        )
        flags = os.O_PATH | os.O_CLOEXEC | os.O_NOFOLLOW
        state = null = None
        try:
            state = os.open(state_dir, flags | os.O_DIRECTORY)
            null = os.open("/dev/null", flags)
            for directory in [state, *workspace_fds]:
                syscall(
                    ADD_RULE,
                    rule,
                    RULE_PATH_BENEATH,
                    ctypes.c_char_p(struct.pack("=Qi", WRITABLE_TREE, directory)),
                    0,
                )
            syscall(
                ADD_RULE,
                rule,
                RULE_PATH_BENEATH,
                ctypes.c_char_p(struct.pack("=Qi", WRITE_FILE, null)),
                0,
            )
            if LIBC.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
                code = ctypes.get_errno()
                raise OSError(code, os.strerror(code))
            syscall(RESTRICT_SELF, rule, 0)
        finally:
            for fd in (null, state, rule):
                if fd is not None:
                    os.close(fd)
    except OSError as exc:
        raise RuntimeError("Unable to enable the Nexus Landlock write policy") from exc
