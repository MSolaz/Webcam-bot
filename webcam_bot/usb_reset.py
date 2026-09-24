"""
Reset USB real de la webcam.

Cuando una webcam se queda "colgada" (LED encendido fijo, no responde a
v4l2), reabrir el dispositivo desde el software no siempre basta: el
propio controlador USB puede estar bloqueado. La solución sin desenchufar
físicamente el cable es un reset a nivel de puerto USB, vía el ioctl
USBDEVFS_RESET del kernel de Linux — el mismo mecanismo que usa la
utilidad `usbreset`.

Requiere que el contenedor tenga acceso al árbol /dev/bus/usb (ver
docker-compose.yml: volumes + device_cgroup_rules).
"""

import fcntl
import os

__all__ = ["USBResetError", "find_usb_device_node", "reset_usb_camera"]

# _IO('U', 20) del kernel de Linux (<linux/usbdevice_fs.h>)
USBDEVFS_RESET = 21780


class USBResetError(Exception):
    pass


def _walk_up_for_usb_device(start_path: str, max_levels: int = 8) -> str:
    """Sube desde start_path hasta encontrar un directorio con
    busnum/devnum (el dispositivo USB real, no una interfaz suya) y
    devuelve la ruta /dev/bus/usb/BBB/DDD correspondiente. Separado de
    find_usb_device_node() para poder probarlo con rutas sintéticas."""

    path = start_path
    for _ in range(max_levels):
        busnum_file = os.path.join(path, "busnum")
        devnum_file = os.path.join(path, "devnum")
        if os.path.isfile(busnum_file) and os.path.isfile(devnum_file):
            with open(busnum_file) as f:
                busnum = int(f.read().strip())
            with open(devnum_file) as f:
                devnum = int(f.read().strip())
            return f"/dev/bus/usb/{busnum:03d}/{devnum:03d}"

        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent

    raise USBResetError(
        f"No se pudo localizar el dispositivo USB real a partir de "
        f"'{start_path}' en sysfs."
    )


def find_usb_device_node(camera_device: str) -> str:
    """A partir de /dev/videoN, localiza el nodo USB real que hay que
    resetear (/dev/bus/usb/BBB/DDD), recorriendo hacia arriba el árbol
    de sysfs hasta encontrar el directorio del dispositivo USB (el que
    tiene los archivos busnum/devnum, no el de la interfaz)."""

    video_name = os.path.basename(camera_device)
    sysfs_link = f"/sys/class/video4linux/{video_name}/device"

    real_path = os.path.realpath(sysfs_link)
    if not os.path.isdir(real_path):
        raise USBResetError(
            f"No se encontró la ruta sysfs de '{camera_device}' "
            f"({sysfs_link}). ¿Sigue conectada la cámara?"
        )

    return _walk_up_for_usb_device(real_path)


def reset_usb_camera(camera_device: str) -> str:
    """Realiza el reset USB. Devuelve la ruta del nodo reseteado.
    Lanza USBResetError si algo falla. Bloqueante: llamar vía
    asyncio.to_thread."""

    node = find_usb_device_node(camera_device)

    try:
        fd = os.open(node, os.O_WRONLY)
    except OSError as exc:
        raise USBResetError(
            f"No se pudo abrir {node} para el reset ({exc}). ¿Está "
            "/dev/bus/usb montado en el contenedor con permisos "
            "suficientes? (ver docker-compose.yml)"
        ) from exc

    try:
        fcntl.ioctl(fd, USBDEVFS_RESET, 0)
    except OSError as exc:
        raise USBResetError(f"El reset USB de {node} falló ({exc}).") from exc
    finally:
        os.close(fd)

    return node
