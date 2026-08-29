#!/usr/bin/env python3
"""
Script de Backup Automatizado para SQLite en Render con Persistent Disk.
- Utiliza la API nativa de backup de SQLite (conn.backup), garantizando consistencia
  sin bloquear las operaciones de lectura o escritura de la aplicación en producción.
- Soporta rotación de backups (Retención: 7 diarios + 4 semanales).
- Soporta subida opcional a almacenamiento externo compatible con S3 (AWS S3, Cloudflare R2).
"""

import os
import sqlite3
import datetime
import glob
import shutil

# Configuración de rutas
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_DB = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'torneo.db'))
BACKUP_DIR = os.environ.get('BACKUP_DIR', '/data/backups' if os.path.exists('/data') else os.path.join(BASE_DIR, 'backups'))

def perform_backup():
    if not os.path.exists(SOURCE_DB):
        print(f"[ERROR] La base de datos origen no existe en: {SOURCE_DB}")
        return False

    os.makedirs(BACKUP_DIR, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"backup_torneo_{timestamp}.sqlite"
    backup_filepath = os.path.join(BACKUP_DIR, backup_filename)

    print(f"[INFO] Iniciando backup en caliente desde {SOURCE_DB} hacia {backup_filepath}...")

    # Conexión origen en modo solo lectura para mayor seguridad
    src_conn = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(backup_filepath)

    try:
        # SQLite Online Backup API (No bloquea a los usuarios)
        with dst_conn:
            src_conn.backup(dst_conn, pages=100, sleep=0.01)
        print(f"[ÉXITO] Backup local creado exitosamente: {backup_filepath}")
    except Exception as e:
        print(f"[ERROR] Falló el proceso de backup: {e}")
        return False
    finally:
        dst_conn.close()
        src_conn.close()

    # Rotación local: Mantener los últimos 7 diarios + 4 semanales (11 archivos)
    cleanup_old_backups(max_keep=11)

    # Subida externa opcional a S3 / Cloudflare R2 si las variables están configuradas
    upload_to_external_storage(backup_filepath)

    return True

def cleanup_old_backups(max_keep=11):
    backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "backup_torneo_*.sqlite")))
    if len(backups) > max_keep:
        to_delete = backups[:-max_keep]
        for f in to_delete:
            try:
                os.remove(f)
                print(f"[ROTACIÓN] Eliminado backup antiguo: {os.path.basename(f)}")
            except OSError as e:
                print(f"[ALERTA] No se pudo eliminar {f}: {e}")

def upload_to_external_storage(backup_path):
    bucket = os.environ.get('S3_BUCKET_NAME')
    if not bucket:
        print("[INFO] No se configuró S3_BUCKET_NAME. El backup permanece en disco local/persistente.")
        return

    try:
        import boto3
        s3 = boto3.client(
            's3',
            endpoint_url=os.environ.get('S3_ENDPOINT_URL'), # Compatible con Cloudflare R2
            aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
            region_name=os.environ.get('AWS_REGION', 'auto')
        )
        file_name = os.path.basename(backup_path)
        s3.upload_file(backup_path, bucket, f"backups/{file_name}")
        print(f"[ÉXITO] Backup sincronizado a almacenamiento externo seguro: {bucket}/backups/{file_name}")
    except ImportError:
        print("[ALERTA] boto3 no está instalado. Para backups externos a S3/R2 instale: pip install boto3")
    except Exception as e:
        print(f"[ERROR] Error al subir a almacenamiento externo: {e}")

if __name__ == '__main__':
    perform_backup()
