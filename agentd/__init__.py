"""agentd: the always-on service. It runs the `harness` command as a subprocess for each job.

Nothing here touches the request code. Standard library only, because the service runs in native Termux Python.
"""
