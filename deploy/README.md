# Running DQ Workbench as a daily job

The CLI (`dq_monitor.py`) runs every configured stage once and exits. Here it runs once a day from a
systemd timer in its own small LXD container next to the DHIS2 instance. The heavy work (validation
rule analysis, outlier detection, integrity checks, imports) happens inside DHIS2 and Postgres, so the
container needs little memory.

The CLI exits with status 1 if any stage reports errors or an import is not `OK`, so a bad run shows up
as a failed unit (`systemctl --failed`).

Files:

| File | Purpose |
|---|---|
| `install.sh` | Installs or updates the tool at a git ref, creates the service user, venv, config/log dirs and enables the timer |
| `dq-workbench.service` | One-shot run of `dq_monitor.py --config /etc/dq-workbench/config.yml` as user `dqworkbench` |
| `dq-workbench.timer` | Daily at 01:30 Asia/Yangon, catches up a missed run after a reboot |

## 1. Create the container (on the LXD host)

Pick a free address on the DHIS2 bridge (`lxc list` shows the ones in use):

```bash
lxc launch ubuntu:24.04 dqworkbench \
  -c limits.memory=1GiB -c boot.autostart=true \
  --network lxdbr1
lxc config device override dqworkbench eth0 ipv4.address=172.19.2.40
lxc restart dqworkbench
lxc list dqworkbench
```

## 2. Let it reach the DHIS2 instance directly

Call Tomcat over the bridge, not through the public proxy. That avoids TLS, proxy timeouts on long
outlier runs and proxy access logging. In the `hmis` container:

```bash
lxc exec hmis -- ufw allow from 172.19.2.40 to any port 8080 proto tcp
```

Check it from the new container (the context path should match the instance name):

```bash
lxc exec dqworkbench -- curl -s -o /dev/null -w '%{http_code}\n' http://<hmis-ip>:8080/hmis/api/ping
```

## 3. Install

```bash
lxc file push deploy/install.sh dqworkbench/root/install.sh
lxc exec dqworkbench -- bash /root/install.sh main      # or a tag, e.g. v1.2.0
```

## 4. Config

Copy the working config into the container and point it at Tomcat:

```bash
lxc file push hmis_config.yml dqworkbench/etc/dq-workbench/config.yml
lxc exec dqworkbench -- bash -c 'chown root:dqworkbench /etc/dq-workbench/config.yml && chmod 640 /etc/dq-workbench/config.yml'
```

In `/etc/dq-workbench/config.yml`:

```yaml
server:
  base_url: http://<hmis-ip>:8080/hmis   # Tomcat on the bridge, not https://mm.dhis2.net/hmis
  d2_token: <dq_workbench_bot token>     # keep using the dedicated bot user
  log_file: /var/log/dq-workbench/dq.log # or remove it and rely on journald
```

The service can only write to `/var/log/dq-workbench`. A `log_file` anywhere else (e.g. `/tmp/dq.log`
from a desktop config) goes to the unit's private `/tmp` and is lost.

## 5. First run

```bash
lxc exec dqworkbench -- systemctl start dq-workbench.service     # blocks until the run finishes
lxc exec dqworkbench -- journalctl -u dq-workbench --no-pager -n 50
lxc exec dqworkbench -- systemctl list-timers dq-workbench.timer
```

## Operating

- **Change the time:** edit `OnCalendar` in `/etc/systemd/system/dq-workbench.timer`, then
  `systemctl daemon-reload`. Keep it before the nightly analytics table generation and clear of the
  scheduled DATA_INTEGRITY job and backups.
- **Update the tool:** `bash /opt/dq-workbench/deploy/install.sh <ref>`. The config is left alone.
- **Did last night's run work?** `systemctl status dq-workbench.service` (exit status) and
  `journalctl -u dq-workbench --since yesterday`.
