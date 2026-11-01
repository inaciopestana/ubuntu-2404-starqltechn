#!/usr/bin/env bash
set -e

K="${1:-kernel-source/.config}"

echo "=== Ubuntu 24.04 kernel requirements ==="

for opt in \
 CONFIG_DEVTMPFS \
 CONFIG_CGROUPS \
 CONFIG_INOTIFY_USER \
 CONFIG_SIGNALFD \
 CONFIG_TIMERFD \
 CONFIG_EPOLL \
 CONFIG_UNIX \
 CONFIG_SYSFS \
 CONFIG_PROC_FS \
 CONFIG_FHANDLE \
 CONFIG_NET_NS \
 CONFIG_USER_NS \
 CONFIG_IPV6 \
 CONFIG_TMPFS_XATTR \
 CONFIG_TMPFS_POSIX_ACL \
 CONFIG_EXT4_FS_POSIX_ACL \
 CONFIG_SECCOMP \
 CONFIG_SECCOMP_FILTER \
 CONFIG_CGROUP_SCHED \
 CONFIG_FAIR_GROUP_SCHED \
 CONFIG_CFS_BANDWIDTH \
 CONFIG_BPF \
 CONFIG_BPF_SYSCALL \
 CONFIG_CGROUP_BPF \
 CONFIG_SECURITY \
 CONFIG_SECURITYFS \
 CONFIG_SECURITY_PATH \
 CONFIG_SECURITY_APPARMOR
do
    printf "%-38s " "$opt"
    if grep -q "^${opt}=y" "$K"; then
        echo "OK"
    else
        echo "MISSING"
    fi
done

echo
echo "=== Extra recommended ==="

for opt in \
 CONFIG_AUTOFS4_FS \
 CONFIG_BLK_DEV_BSG \
 CONFIG_CHECKPOINT_RESTORE \
 CONFIG_BINFMT_MISC \
 CONFIG_MEMBARRIER
do
    grep "^${opt}=" "$K" || echo "$opt missing"
done
