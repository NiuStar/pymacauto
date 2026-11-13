"""Public input boundaries shared by the SDK and native bridge."""

def validate_pid(pid):
    # Darwin pid_t is a signed 32-bit integer; reject group/all-process forms.
    if isinstance(pid, bool) or not isinstance(pid, int) or not 1 <= pid <= 2147483647:
        raise ValueError('pid must be an integer between 1 and 2147483647')
    return pid
