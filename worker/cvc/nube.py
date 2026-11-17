"""Cliente mínimo de Supabase (Auth + PostgREST + Storage) para el proceso de carga."""
import keyring
import requests

DOMINIO = "@tiemposdac.local"


class Supabase:
    def __init__(self, cfg: dict):
        if not cfg.get("url") or not cfg.get("anon_key"):
            raise RuntimeError("Falta url / anon_key de Supabase en worker/config.toml")
        self.url, self.key, self.bucket = cfg["url"].rstrip("/"), cfg["anon_key"], cfg.get("bucket", "cvc")
        clave = keyring.get_password(cfg["servicio_credenciales"], cfg["usuario"])
        if not clave:
            raise RuntimeError(f"No hay contraseña del usuario '{cfg['usuario']}' en keyring '{cfg['servicio_credenciales']}'")
        r = requests.post(f"{self.url}/auth/v1/token?grant_type=password", timeout=30,
                          headers={"apikey": self.key},
                          json={"email": cfg["usuario"] + DOMINIO, "password": clave})
        if r.status_code != 200:
            raise ConnectionError(f"Supabase rechazó el ingreso del usuario de sistema: {r.text[:200]}")
        self.token = r.json()["access_token"]
        self.h = {"apikey": self.key, "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    @staticmethod
    def _ok(r):
        if r.status_code >= 300:
            raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else None

    def leer(self, tabla: str, filtro: str = "") -> list[dict]:
        return self._ok(requests.get(f"{self.url}/rest/v1/{tabla}?select=*{filtro}", headers=self.h, timeout=60))

    def insertar(self, tabla: str, datos: dict) -> dict:
        h = {**self.h, "Prefer": "return=representation"}
        return self._ok(requests.post(f"{self.url}/rest/v1/{tabla}", headers=h, json=datos, timeout=60))[0]

    def actualizar(self, tabla: str, filtro: str, datos: dict):
        return self._ok(requests.patch(f"{self.url}/rest/v1/{tabla}?{filtro}", headers=self.h, json=datos, timeout=60))

    def rpc(self, funcion: str, args: dict):
        return self._ok(requests.post(f"{self.url}/rest/v1/rpc/{funcion}", headers=self.h, json=args, timeout=300))

    def subir(self, ruta: str, contenido: bytes, tipo: str):
        """Sube (o reemplaza) un archivo en el bucket privado del módulo."""
        h = {"apikey": self.key, "Authorization": f"Bearer {self.token}", "Content-Type": tipo,
             "x-upsert": "true", "cache-control": "no-cache"}
        return self._ok(requests.post(f"{self.url}/storage/v1/object/{self.bucket}/{ruta}", headers=h,
                                      data=contenido, timeout=600))
