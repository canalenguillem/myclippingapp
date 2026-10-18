// Registro de motivos gráficos. Cada motivo es una función ({id, item, t0, at, t1}) → {html, css, script} con los
// tiempos YA en tiempo de salida. Añadir un motivo = una entrada aquí + su esquema en `contract.mjs`.
import { keywordMotif } from "./keyword.mjs";

export const MOTIFS = {
  keyword: keywordMotif,
};
