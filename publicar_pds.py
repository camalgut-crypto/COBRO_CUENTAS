"""Publica la herramienta "PD's, Cosecha y Cono de Cobro" en el repositorio PDS_COSECHA_CONO_COBRO.

Las dos herramientas usan el mismo código (public/) y los mismos usuarios y datos de Supabase; solo cambia
HERRAMIENTA en config.js. Este script copia public/ (sin public/local) a un clon del otro repositorio, cambia
HERRAMIENTA a 'pds', y hace commit y push. GitHub Pages publica la carpeta public/ de ese repositorio.

Uso (desde la carpeta del proyecto):  .venv\\Scripts\\python.exe publicar_pds.py ["mensaje del commit"]
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ.parent / "PDS Cosecha Cono Cobro"          # clon de PDS_COSECHA_CONO_COBRO (fuera de este repositorio)
REPO = "https://github.com/camalgut-crypto/PDS_COSECHA_CONO_COBRO.git"
FIRMA = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def git(*args, cwd=DESTINO):
    subprocess.run(["git", *args], cwd=cwd, check=True)


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else "Actualiza la herramienta de PD's"
    if not (DESTINO / ".git").exists():
        DESTINO.mkdir(parents=True, exist_ok=True)
        git("init", "-b", "main")
        git("remote", "add", "origin", REPO)
    pub = DESTINO / "public"
    if pub.exists():
        shutil.rmtree(pub)
    shutil.copytree(RAIZ / "public", pub, ignore=shutil.ignore_patterns("local"))
    cfg = (pub / "config.js").read_text(encoding="utf-8")
    cfg, n = re.subn(r"HERRAMIENTA:\s*'cuentas'", "HERRAMIENTA: 'pds'", cfg)
    assert n == 1, "config.js no tiene HERRAMIENTA: 'cuentas'"
    (pub / "config.js").write_text(cfg, encoding="utf-8")
    wf = DESTINO / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    shutil.copy2(RAIZ / ".github" / "workflows" / "pages.yml", wf / "pages.yml")
    (DESTINO / "README.md").write_text(
        "# PD's, Cosecha y Cono de Cobro\n\nSeguimiento 1PD a 6PD, mora por cuota, primeros pagos por cosecha y cono de "
        "cobranza (Nicaragua).\n\nEl código se mantiene en el proyecto *Cosechas vs Cobro* (repositorio COBRO_CUENTAS) y se "
        "publica aquí con `publicar_pds.py`; los datos los sube el mismo proceso de carga al bucket privado de Supabase.\n",
        encoding="utf-8")
    git("add", "-A")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=DESTINO).returncode == 0:
        print("Sin cambios para publicar")
        return
    git("commit", "-q", "-m", f"{msg}\n\n{FIRMA}")
    git("push", "-q", "-u", "origin", "main")
    print("Publicado en", REPO)


if __name__ == "__main__":
    main()
