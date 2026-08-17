# Despliegue en PythonAnywhere con SQLite

La app ya **no depende del MySQL externo de Hostinger**. Por defecto usa un
SQLite local en `instance/emex.db`, dentro del mismo servidor de PythonAnywhere.

## Poner la página de vuelta en línea

En una consola Bash de PythonAnywhere:

```bash
cd ~/appRegistros
git pull
source venv/bin/activate
pip install -r requirements.txt      # añade Flask-Compress
python3 run_migration.py --yes       # crea el esquema SQLite y el admin inicial
```

Después, en la pestaña **Web** → botón **Reload**. Verificar con:

```
https://<tu-dominio>/healthz     ->  {"ok": true, "db": "sqlite"}
```

No hace falta editar el `.env` del servidor: si `DATABASE_URL` sigue apuntando a
MySQL, la app la ignora y registra un aviso en el error log.

## Acceso inicial

La base arranca vacía. Al primer arranque se crea automáticamente el usuario
admin con `ADMIN_EMAIL` / `ADMIN_PASSWORD` del `.env` (por defecto
`admin@emex.mx` / `admin123`). **Cambiar esa contraseña al entrar.**

## Variables de entorno relevantes

| Variable | Valor por defecto | Para qué sirve |
|---|---|---|
| `SQLITE_PATH` | `instance/emex.db` | Ruta alterna del archivo SQLite |
| `USE_EXTERNAL_DB` | `0` | `1` + `DATABASE_URL` para volver a MySQL |
| `AUTO_SCHEMA_FIX` | `1` | Crea/parcha el esquema al arrancar |
| `AUTO_SEED_ADMIN` | `1` | Crea el admin sólo si no hay ningún usuario |

## Recuperar los datos del MySQL

Cuando Hostinger desbloquee la cuenta (o desde cualquier respaldo), copiar los
datos al SQLite:

```bash
python3 tools/import_to_sqlite.py "mysql+pymysql://usuario:PASS@srv744.hstgr.io:3306/u312201851_emex_app?charset=utf8mb4"
```

La contraseña debe ir *url-encoded* si trae `@ : / = > #`. El script omite las
tablas que ya tengan datos; con `--force` las vacía y las reemplaza.

## Respaldos

SQLite es un solo archivo: conviene bajarlo con cierta frecuencia.

```bash
cd ~/appRegistros && cp instance/emex.db instance/backup_$(date +%F).db
```

## Nota sobre PythonAnywhere

El `/home` de PythonAnywhere es un sistema de archivos en red, así que SQLite
funciona pero no conviene para mucha escritura concurrente (por eso el código
usa `busy_timeout=30000` y **no** activa WAL). Si más adelante la carga crece,
la alternativa sin llamadas externas es el MySQL propio de PythonAnywhere
(`<usuario>.mysql.pythonanywhere-services.com`): basta con poner esa URL en
`DATABASE_URL` y `USE_EXTERNAL_DB=1`, e importar el SQLite con el mismo criterio.
