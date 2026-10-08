"""Fontes de referência usadas na validação.

`SigaReferencias` lê as tabelas do SIGA (somente leitura) e o dicionário `ocr.dominio`.
`ReferenciasEstaticas` serve para testes e para rodar sem banco."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .texto import Ref


@dataclass
class ReferenciasEstaticas:
    municipios: list[Ref] = field(default_factory=list)
    procedimentos: list[Ref] = field(default_factory=list)
    intervencoes: list[Ref] = field(default_factory=list)
    finalidades: list[Ref] = field(default_factory=list)
    sistemas_irrigacao: list[Ref] = field(default_factory=list)
    culturas: list[Ref] = field(default_factory=list)
    dominios: dict[str, list[Ref]] = field(default_factory=dict)  # demais listas do formulário
    pessoas: dict[str, Ref] = field(default_factory=dict)  # dígitos -> pessoa
    processos: dict[str, Ref] = field(default_factory=dict)  # uuid -> processo
    poligonos: dict[int, bool] = field(default_factory=dict)  # municipio_id -> resultado fixo

    def pessoa_por_documento(self, digitos: str) -> Ref | None:
        return self.pessoas.get(digitos)

    def dominio(self, tipo: str) -> list[Ref]:
        if tipo == "sistema_irrigacao":
            return self.sistemas_irrigacao
        if tipo == "cultura":
            return self.culturas
        return self.dominios.get(tipo, [])

    def processo_por_uuid(self, uuid: str) -> Ref | None:
        return self.processos.get(uuid)

    def ponto_no_municipio(self, lat: float, lon: float, municipio_id: int | None) -> bool | None:
        if municipio_id is None:
            return None
        return self.poligonos.get(municipio_id)


class SigaReferencias:
    """Carrega listas de referência do SIGA com cache em memória (padrão: 10 minutos)."""

    def __init__(self, engine: Engine, uf: str = "PI", srid_entrada: int = 4674, ttl: int = 600):
        self.engine = engine
        self.uf = uf
        self.srid = srid_entrada
        self.ttl = ttl
        self._cache: dict[str, tuple[float, list[Ref]]] = {}
        self._lock = threading.Lock()

    def _lista(self, nome: str, sql: str, **params) -> list[Ref]:
        with self._lock:
            hit = self._cache.get(nome)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
        with self.engine.connect() as c:
            linhas = c.execute(text(sql), params).mappings().all()
        refs = [Ref(r["id"], r["nome"], list(r.get("sinonimos") or [])) for r in linhas]
        with self._lock:
            self._cache[nome] = (time.time(), refs)
        return refs

    def limpar_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def municipios(self) -> list[Ref]:
        return self._lista(
            "municipios",
            "SELECT m.id, m.nome FROM public.core_municipio m "
            "JOIN public.core_estado e ON e.id = m.estado_id WHERE e.uf = :uf",
            uf=self.uf,
        )

    @property
    def procedimentos(self) -> list[Ref]:
        return self._lista("procedimentos", "SELECT id, nome FROM public.protocolo_procedimento WHERE ativo")

    @property
    def intervencoes(self) -> list[Ref]:
        return self._lista("intervencoes", "SELECT id, nome FROM public.outorga_tipointervencao WHERE ativo")

    @property
    def finalidades(self) -> list[Ref]:
        return self._lista("finalidades", "SELECT id, nome FROM public.outorga_tipofinalidadeuso WHERE ativo")

    @property
    def sistemas_irrigacao(self) -> list[Ref]:
        return self.dominio("sistema_irrigacao")

    @property
    def culturas(self) -> list[Ref]:
        return self.dominio("cultura")

    def dominio(self, tipo: str) -> list[Ref]:
        return self._lista(
            f"dominio:{tipo}",
            "SELECT id, valor AS nome, sinonimos FROM ocr.dominio WHERE tipo = :tipo AND ativo ORDER BY id",
            tipo=tipo,
        )

    def pessoa_por_documento(self, digitos: str) -> Ref | None:
        if len(digitos) == 11:
            sql = (
                "SELECT p.id, p.nome FROM public.core_pessoafisica pf "
                "JOIN public.core_pessoa p ON p.id = pf.pessoa_ptr_id "
                "WHERE regexp_replace(pf.cpf, '\\D', '', 'g') = :d LIMIT 1"
            )
        elif len(digitos) == 14:
            sql = (
                "SELECT p.id, COALESCE(NULLIF(pj.razao_social, ''), p.nome) AS nome "
                "FROM public.core_pessoajuridica pj JOIN public.core_pessoa p ON p.id = pj.pessoa_ptr_id "
                "WHERE regexp_replace(pj.cnpj, '\\D', '', 'g') = :d LIMIT 1"
            )
        else:
            return None
        with self.engine.connect() as c:
            r = c.execute(text(sql), {"d": digitos}).mappings().first()
        return Ref(r["id"], r["nome"]) if r else None

    def processo_por_uuid(self, uuid: str) -> Ref | None:
        with self.engine.connect() as c:
            r = c.execute(
                text("SELECT id, numero_processo AS nome FROM public.protocolo_processo WHERE uuid = CAST(:u AS uuid)"),
                {"u": uuid},
            ).mappings().first()
        return Ref(r["id"], r["nome"]) if r else None

    def ponto_no_municipio(self, lat: float, lon: float, municipio_id: int | None) -> bool | None:
        if municipio_id is None:
            return None
        sql = text(
            """
            SELECT CASE
              WHEN m.geom IS NULL THEN NULL
              WHEN ST_SRID(m.geom) = 0 THEN ST_Intersects(m.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 0))
              ELSE ST_Intersects(m.geom, ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), :srid), ST_SRID(m.geom)))
            END AS dentro
            FROM public.core_municipio m WHERE m.id = :id
            """
        )
        with self.engine.connect() as c:
            r = c.execute(sql, {"lat": lat, "lon": lon, "srid": self.srid, "id": municipio_id}).first()
        return None if r is None else r[0]
