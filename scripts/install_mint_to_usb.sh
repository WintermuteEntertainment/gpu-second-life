#!/bin/bash
# Copies the running Mint live system to the USB drive on Noodlecart. Run as root in the live session.
# Erases only the drive that passes every check below, and doesn't touch the Windows drive or firmware boot entries.
set -euo pipefail
MODEL_WANTED="TEAM TM8PS7256G"
NEW_USER="tim"
D=/dev/sdb

model=$(lsblk -dn -o MODEL "$D" | xargs)
tran=$(lsblk -dn -o TRAN "$D")
size=$(lsblk -dbn -o SIZE "$D")
root_src=$(findmnt -n -o SOURCE /cdrom || true)
echo "target $D: model '$model', transport $tran, size $size bytes; live media $root_src"
[ "$model" = "$MODEL_WANTED" ] || { echo "ABORT: wrong model"; exit 3; }
[ "$tran" = "usb" ] || { echo "ABORT: not USB"; exit 3; }
[ "$size" -gt 200000000000 ] && [ "$size" -lt 300000000000 ] || { echo "ABORT: unexpected size"; exit 3; }
[ "$(lsblk -nr -o MOUNTPOINT "$D" | grep -c . || true)" = "0" ] || { echo "ABORT: target is mounted"; exit 3; }
findmnt -n -o SOURCE /cdrom | grep -q '^/dev/sdb' && { echo "ABORT: live media is on target"; exit 3; }
[ -d /rofs/etc ] || { echo "ABORT: live image not found"; exit 3; }

echo "=== partitioning"
wipefs -a "$D" >/dev/null
parted -s "$D" mklabel gpt mkpart ESP fat32 1MiB 513MiB set 1 esp on mkpart root ext4 513MiB 100%
udevadm settle; sleep 2
mkfs.vfat -F32 -n MINTEFI "${D}1" >/dev/null
mkfs.ext4 -q -F -L mint-gpudoc "${D}2"
M=/mnt/target
mkdir -p "$M"; mount "${D}2" "$M"; mkdir -p "$M/boot/efi"; mount "${D}1" "$M/boot/efi"

echo "=== copying system"
rsync -aHAX --numeric-ids --info=stats1 --exclude='/cdrom/*' /rofs/ "$M/"
K=$(uname -r)
cp /cdrom/casper/vmlinuz "$M/boot/vmlinuz-$K" 2>/dev/null || true
[ -d "$M/lib/modules/$K" ] || { echo "ABORT: no modules for $K"; exit 3; }

ROOT_UUID=$(blkid -s UUID -o value "${D}2"); EFI_UUID=$(blkid -s UUID -o value "${D}1")
cat > "$M/etc/fstab" <<EOF
UUID=$ROOT_UUID / ext4 defaults,noatime 0 1
UUID=$EFI_UUID /boot/efi vfat umask=0077 0 1
EOF
echo noodlecart-mint > "$M/etc/hostname"
printf '127.0.0.1 localhost\n127.0.1.1 noodlecart-mint\n' > "$M/etc/hosts"
rm -f "$M/etc/machine-id" "$M/var/lib/dbus/machine-id"; : > "$M/etc/machine-id"
rm -f "$M/etc/resolv.conf"; cp -L /etc/resolv.conf "$M/etc/resolv.conf"
MANIFEST=/cdrom/casper/filesystem.manifest-remove
[ -f "$MANIFEST" ] && cut -d' ' -f1 "$MANIFEST" > "$M/tmp/remove.list" || : > "$M/tmp/remove.list"
AK=$(cat /home/mint/.ssh/authorized_keys)

for f in dev dev/pts proc sys run sys/firmware/efi/efivars; do mountpoint -q "/$f" && { mkdir -p "$M/$f"; mount --bind "/$f" "$M/$f"; }; done

cat > "$M/tmp/setup.sh" <<CHROOT
#!/bin/bash
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive
K=$K
echo "=== removing live-only packages"
apt-get purge -y \$(cat /tmp/remove.list) >/dev/null 2>&1 || echo "note: some live packages not removed"
echo "=== packages"
apt-get update -qq
apt-get install -y -qq grub-efi-amd64 grub-efi-amd64-signed shim-signed efibootmgr openssh-server linux-headers-\$K >/dev/null || echo "note: package step had errors"
echo "=== user"
id $NEW_USER >/dev/null 2>&1 || useradd -m -s /bin/bash -G sudo,adm,video,render,plugdev $NEW_USER
passwd -l $NEW_USER >/dev/null
mkdir -p /home/$NEW_USER/.ssh; echo "$AK" > /home/$NEW_USER/.ssh/authorized_keys
chmod 700 /home/$NEW_USER/.ssh; chmod 600 /home/$NEW_USER/.ssh/authorized_keys; chown -R $NEW_USER: /home/$NEW_USER/.ssh
echo "$NEW_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-$NEW_USER; chmod 440 /etc/sudoers.d/90-$NEW_USER
rm -f /etc/ssh/ssh_host_*; ssh-keygen -A >/dev/null; systemctl enable ssh >/dev/null 2>&1
ufw allow from 192.168.2.0/24 to any port 22 proto tcp >/dev/null 2>&1 || true
echo "=== boot files"
update-initramfs -c -k \$K >/dev/null 2>&1 || update-initramfs -u -k \$K >/dev/null
grub-install --target=x86_64-efi --efi-directory=/boot/efi --removable --no-nvram --recheck
sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=3/' /etc/default/grub
echo 'GRUB_DISABLE_OS_PROBER=true' >> /etc/default/grub
update-grub 2>&1 | tail -3
CHROOT
chmod +x "$M/tmp/setup.sh"
chroot "$M" /tmp/setup.sh
rm -f "$M/tmp/setup.sh" "$M/tmp/remove.list"
rm -f "$M/etc/resolv.conf"; ln -s ../run/systemd/resolve/stub-resolv.conf "$M/etc/resolv.conf"
sync
echo "=== checks"
ls -la "$M/boot/efi/EFI/BOOT/" | tail -3
ls "$M/boot" | grep -E 'vmlinuz|initrd' | head
grep -c menuentry "$M/boot/grub/grub.cfg"
id -u "$NEW_USER" >/dev/null 2>&1; chroot "$M" id "$NEW_USER"
df -h "$M" | tail -1
for f in sys/firmware/efi/efivars run sys proc dev/pts dev; do mountpoint -q "$M/$f" && umount "$M/$f"; done
umount "$M/boot/efi"; umount "$M"; sync
echo "=== sda untouched"; lsblk -o NAME,SIZE,FSTYPE /dev/sda
echo "=== INSTALL DONE"
