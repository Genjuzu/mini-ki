/**
 * Daumen-Ablauf für AVA.
 *
 * AVA antwortet selbst. Mini-KI sucht nur. Trifft der Speicher, kommt der
 * Text und, wenn vorhanden, das Audio zurück. Sonst legt AVA die eigene
 * Antwort mit Daumen hoch ab und hängt das Opus-Audio an. Daumen runter
 * auf einen Treffer sperrt nur diese Frage; der Eintrag bleibt für seine
 * anderen Formulierungen gut.
 */

import { MiniKiClient, type AnfrageErgebnis, type AnhangMeta, type Herkunft } from "./client.js";

export interface SelbstAntwort {
  text: string;
  audio?: Uint8Array;
}

export interface DaumenErgebnis {
  id: string | null;
  herkunft: Herkunft;
  text: string;
  audio: Uint8Array | null;
}

export async function daumenAblauf(
  client: MiniKiClient,
  frage: string,
  erzeugen: (frage: string) => Promise<SelbstAntwort>,
): Promise<DaumenErgebnis> {
  const treffer = await client.anfragen(frage, { nurSuchen: true });
  if (treffer.herkunft === "speicher" && treffer.id) {
    return {
      id: treffer.id,
      herkunft: "speicher",
      text: treffer.text,
      audio: await audioAusTreffer(client, treffer),
    };
  }
  const erzeugt = await erzeugen(frage);
  const angelegt = await client.eintragAnlegen(frage, erzeugt.text);
  await client.bewerten(angelegt.id, "gut");
  if (erzeugt.audio !== undefined) {
    await client.anhangSetzen(angelegt.id, "audio", erzeugt.audio);
  }
  return {
    id: angelegt.id,
    herkunft: "neu",
    text: erzeugt.text,
    audio: erzeugt.audio ?? null,
  };
}

/** Daumen runter. `frage` ist die Anfrage, die diesen Treffer nicht mehr bekommen soll. */
export function daumenRunter(client: MiniKiClient, id: string, frage: string): Promise<{ ok: true }> {
  return client.bewerten(id, "schlecht", { frage, herkunft: "speicher" });
}

async function audioAusTreffer(client: MiniKiClient, treffer: AnfrageErgebnis): Promise<Uint8Array | null> {
  if (!treffer.id || !hatAudio(treffer.anhaenge)) {
    return null;
  }
  const gelesen = await client.anhangLesen(treffer.id, "audio");
  return gelesen.daten;
}

function hatAudio(anhaenge: AnhangMeta[] | undefined): boolean {
  return (anhaenge ?? []).some((anhang) => anhang.art === "audio");
}
