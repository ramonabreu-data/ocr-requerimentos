"use client";
import { useCallback, useEffect, useRef, useState } from "react";

/** Busca dados e repete a cada `intervalo` ms enquanto `continuar(dados)` for verdadeiro. */
export function usePolling<T>(buscar: () => Promise<T>, continuar: (d: T) => boolean, intervalo = 2500) {
  const [dados, setDados] = useState<T | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const buscarRef = useRef(buscar);
  const continuarRef = useRef(continuar);
  const [versao, setVersao] = useState(0);

  useEffect(() => {
    buscarRef.current = buscar;
    continuarRef.current = continuar;
  });

  useEffect(() => {
    let ativo = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ciclo = async () => {
      try {
        const d = await buscarRef.current();
        if (!ativo) return;
        setDados(d);
        setErro(null);
        if (continuarRef.current(d)) timer = setTimeout(ciclo, intervalo);
      } catch (e) {
        if (!ativo) return;
        setErro(e instanceof Error ? e.message : String(e));
        timer = setTimeout(ciclo, intervalo * 2);
      }
    };
    ciclo();
    return () => {
      ativo = false;
      if (timer) clearTimeout(timer);
    };
  }, [intervalo, versao]);

  const recarregar = useCallback(() => setVersao((v) => v + 1), []);
  return { dados, setDados, erro, recarregar };
}
