#!/bin/sh
# The bucket mount service's start (docker-compose.bucket-mounts.yml): rclone's
# remote control daemon on a Unix socket that only Curio's backend may reach
# (docs/ARCHITECTURE.md, "Bucket mounts"). POSIX sh: the rclone image has
# busybox's.
set -eu

MOUNTS=/mounts
CONTROL=/run/curio-bucket-mounts
SELFTEST=/selftest

# A service that stopped without unmounting (killed, out of memory, a crash)
# left its FUSE mounts under $MOUNTS on the host, dead: each read of one fails
# with "Transport endpoint is not connected". Each is unmounted lazily, the
# deepest first, and the unmount reaches the host and Curio's container too.
awk -v root="$MOUNTS/" 'index($2, root) == 1 { print $2 }' /proc/self/mounts | sort -r |
  while read -r mount_point; do
    echo "unmounting $mount_point, which a stopped service left"
    fusermount3 -uz "$mount_point" || umount -l "$mount_point" ||
      echo "could not unmount $mount_point" >&2
  done

# The control folder: only root may enter it, so only root reaches the socket.
mkdir -p "$CONTROL"
chmod 0700 "$CONTROL"
# rclone does not listen on a socket a stopped service left behind.
rm -f "$CONTROL/rc.sock"

# The self-test's file: Curio's backend mounts $SELFTEST and reads this line
# back through its own container, as node code's account
# (utk_curio/backend/app/discovery/infrastructure/bucket_mounts.py).
echo "curio bucket mounts self-test" > "$SELFTEST/ok"

exec rclone rcd \
  --rc-addr "unix://$CONTROL/rc.sock" \
  --rc-no-auth \
  --use-server-modtime \
  --timeout 1m \
  --contimeout 15s \
  --low-level-retries 3 \
  --log-level INFO \
  --config /config/rclone.conf \
  --cache-dir /tmp/rclone
