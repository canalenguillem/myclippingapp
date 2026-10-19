# Instalar ClippingVideos en Windows 11 (Docker Desktop)

Guía para dejar la app en un Windows 11 de la red de casa, en la unidad **D:**, con **un único puerto** abierto (el del frontend).
La parte de publicar `clipp.enguillem.es` (proxy inverso, DNS, https) la haces tú: solo necesitas apuntar el proxy a `http://<IP-de-este-equipo>:<puerto>`.

## Requisitos

| Qué | Detalle |
|---|---|
| **Docker Desktop** | con el backend WSL 2 (el instalador lo propone). Actívalo en *Settings → General → Start Docker Desktop when you sign in* para que arranque con Windows. |
| **Git** | para clonar y actualizar. |
| **Espacio** | > 30 GB libres en D: (imágenes + vídeos). |
| **Memoria** | un render de HyperFrames usa ~3 GB. Recomendado 16 GB en el equipo; dale a WSL 8 GB (ver abajo). |
| **Clave de OpenAI y de AssemblyAI** | las que usas ahora (no se copian solas). |

### Que Docker use D: (no C:)
1. *Docker Desktop → Settings → Resources → Advanced → Disk image location* → `D:\DockerData` → *Apply & restart*. Aquí viven las imágenes y la base de datos.
2. Los **vídeos** van a `D:\ClippingVideos\media` (lo pone `install.ps1` con `-MediaDir`). Es una carpeta de Windows montada en los contenedores: puede ir algo más lenta que dentro de WSL, pero es la que ves y copias fácilmente.

### Memoria para WSL (recomendado)
Crea `C:\Users\<tú>\.wslconfig`:
```
[wsl2]
memory=8GB
processors=6
```
y ejecuta `wsl --shutdown` (Docker se reinicia solo).

## Instalación

En PowerShell (no hace falta ser administrador, pero sí para crear la regla del cortafuegos):

```powershell
cd D:\
git clone https://github.com/canalenguillem/myclippingapp.git ClippingVideos    # si el repo es privado, te pedirá iniciar sesión en GitHub
cd D:\ClippingVideos
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install.ps1 -MediaDir D:\ClippingVideos\media
```

El script: comprueba Docker, **elige el primer puerto libre desde 8090** (o el que le des con `-Port`), genera los secretos, te pide las claves de API (opcional), crea `.env`, abre el puerto en el cortafuegos **solo para la red local**, construye y arranca. La primera vez tarda 10–20 minutos.

Al acabar te dice la URL (`http://<IP>:<puerto>`). **Anota el puerto**: es el que usará tu proxy.

### Primeros pasos tras instalar
1. Abre la URL y **regístrate: el primer usuario es administrador**.
2. En `.env` pon `ALLOW_REGISTRATION=false` y aplica: `docker compose up -d backend`.
3. En **Canales**, sube el `client_secret.json` y conecta YouTube (ver «OAuth de Google» abajo).

## Publicar con https (lo haces tú)
Tu proxy debe reenviar `https://clipp.enguillem.es` a `http://<IP-de-este-equipo>:<puerto>`. Ajustes que la app necesita en el proxy:

- **Subida de ficheros** hasta 50 MB (`client_max_body_size 50m` en nginx).
- **Sin buffer y con timeout largo** en `/api/` (los logs de los jobs usan SSE): `proxy_buffering off; proxy_read_timeout 1h;`.
- Pasar `Host` y `X-Forwarded-Proto`.

Después, en `.env`:
```
PUBLIC_BASE_URL=https://clipp.enguillem.es
```
y `docker compose up -d backend worker`. **Importante:** con `https` en `PUBLIC_BASE_URL`, las cookies de sesión solo se envían por https; si entras por `http://IP:puerto` ya no podrás iniciar sesión (cámbialo a `http://...` para probar por la LAN, o entra siempre por la URL pública).

## OAuth de Google (YouTube)
En Google Cloud → Credenciales → tu ID de cliente OAuth → *URIs de redireccionamiento autorizados*, añade:
```
https://clipp.enguillem.es/api/youtube/callback
```
(Google solo admite `http` para `localhost`: por una IP de la LAN en `http` no funciona; hay que conectar por la URL https pública.) Mientras la app esté en modo «Testing» el acceso caduca a los 7 días.

## Uso diario
| Qué | Comando (en `D:\ClippingVideos`) |
|---|---|
| Estado | `docker compose ps` |
| Logs | `docker compose logs --tail 100 backend` (o `worker`, `fx_worker`) |
| Parar / arrancar | `docker compose stop` / `docker compose up -d` |
| Actualizar | `.\deploy\windows\update.ps1` (hace copia de la BD antes) |
| Copia de la BD | `.\deploy\windows\backup.ps1` → `D:\ClippingVideos\backups` |

Programar la copia diaria: *Programador de tareas → Crear tarea básica → diaria → `powershell -ExecutionPolicy Bypass -File D:\ClippingVideos\deploy\windows\backup.ps1`*.

## Traer lo que ya tienes en el otro equipo (opcional)
Si quieres conservar usuarios, clips y vídeos:
1. En el equipo actual: `docker compose exec -T mariadb sh -c 'mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --single-transaction clipping' > clipping.sql` y copia la carpeta `media/`.
2. En Windows, con la app ya arrancada: pon `media/` en `D:\ClippingVideos\media` y restaura: `Get-Content clipping.sql | docker compose exec -T mariadb sh -c 'mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" clipping'`.
3. **Usa el mismo `APP_ENCRYPTION_KEY` y `JWT_SECRET` del `.env` antiguo**, o los `client_secret` y tokens de YouTube guardados no se podrán descifrar (tendrías que volver a subirlos y conectar).

## Seguridad antes de abrirla a Internet
- Deja `ALLOW_REGISTRATION=false` en cuanto tengas tu usuario.
- **Aún no hay límite de intentos de login**: con la app pública, alguien podría probar contraseñas sin freno. Usa una contraseña larga y, si puedes, limita el acceso en tu proxy (por IP o con un límite de peticiones a `/api/auth/login`).
- Nunca subas `.env` ni `client_secret*.json` a git (ya están en `.gitignore`).
- Solo se publica un puerto (el del frontend). La API (`8800`) y el servicio de render (`8910`) escuchan solo en `127.0.0.1`.
