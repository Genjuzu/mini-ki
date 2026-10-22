/**
 * Kleiner HTTP-Client für AVA. Der Kern bleibt Python.
 * Basis ist die Adresse des Dienstes, zum Beispiel `http://127.0.0.1:8080`.
 * Der Kunden-Schlüssel geht nur in den Kopf `Authorization` und wird nicht geloggt.
 */

export type Herkunft = "speicher" | "ki" | "neu" | "fehltreffer";
export type Bewertung = "gut" | "schlecht";

export interface AnhangMeta {
  art: string;
  medientyp: string;
  groesse: number;
  pruefsumme: string;
}

export interface AnfrageErgebnis {
  id: string | null;
  herkunft: Herkunft;
  text: string;
  aehnlichkeit?: number;
  anhaenge?: AnhangMeta[];
}

export interface AnfrageWahl {
  verlauf?: string;
  nurSuchen?: boolean;
}

export interface BewertungWahl {
  frage?: string;
  herkunft?: Herkunft;
}

export interface Gesundheit {
  modell: string;
  breite: number;
  anzahl: number;
  einbettung_bereit: boolean;
}

export interface AnhangBytes {
  medientyp: string;
  daten: Uint8Array;
}

export class MiniKiFehler extends Error {
  readonly status: number;

  constructor(status: number, meldung: string) {
    super(meldung);
    this.name = "MiniKiFehler";
    this.status = status;
  }
}

interface AbrufInit {
  method?: string;
  headers?: Record<string, string>;
  body?: string | Uint8Array;
}

interface AbrufAntwort {
  ok: boolean;
  status: number;
  headers: { get(name: string): string | null };
  arrayBuffer(): Promise<ArrayBuffer>;
  json(): Promise<unknown>;
}

declare function fetch(adresse: string, init?: AbrufInit): Promise<AbrufAntwort>;

export class MiniKiClient {
  private readonly basis: string;
  private readonly zugang: string | null;

  constructor(basis: string, zugang?: string) {
    const ohne = basis.replace(/\/+$/, "");
    if (ohne === "") {
      throw new MiniKiFehler(0, "Die Basis-Adresse fehlt.");
    }
    this.basis = ohne;
    this.zugang = zugang && zugang !== "" ? zugang : null;
  }

  gesundheit(): Promise<Gesundheit> {
    return this.json<Gesundheit>("GET", "/v1/gesundheit");
  }

  anfragen(text: string, wahl: AnfrageWahl = {}): Promise<AnfrageErgebnis> {
    const koerper: { text: string; verlauf?: string; nur_suchen?: boolean } = { text };
    if (wahl.verlauf !== undefined) {
      koerper.verlauf = wahl.verlauf;
    }
    if (wahl.nurSuchen !== undefined) {
      koerper.nur_suchen = wahl.nurSuchen;
    }
    return this.json<AnfrageErgebnis>("POST", "/v1/anfragen", koerper);
  }

  eintragAnlegen(frage: string, antwort: string, bewertung?: Bewertung): Promise<{ id: string }> {
    const koerper: { frage: string; antwort: string; bewertung?: Bewertung } = { frage, antwort };
    if (bewertung !== undefined) {
      koerper.bewertung = bewertung;
    }
    return this.json<{ id: string }>("POST", "/v1/eintraege", koerper);
  }

  bewerten(id: string, bewertung: Bewertung, wahl: BewertungWahl = {}): Promise<{ ok: true }> {
    const koerper: { bewertung: Bewertung; frage?: string; herkunft?: Herkunft } = { bewertung };
    if (wahl.frage !== undefined) {
      koerper.frage = wahl.frage;
    }
    if (wahl.herkunft !== undefined) {
      koerper.herkunft = wahl.herkunft;
    }
    return this.json<{ ok: true }>("POST", `/v1/anfragen/${encodeURIComponent(id)}/bewertung`, koerper);
  }

  textSetzen(id: string, text: string): Promise<{ id: string; text: string }> {
    return this.json("PUT", `/v1/anfragen/${encodeURIComponent(id)}/text`, { text });
  }

  neu(id: string, zusatz = ""): Promise<{ id: string; text: string }> {
    return this.json("POST", `/v1/anfragen/${encodeURIComponent(id)}/neu`, { zusatz });
  }

  trennen(id: string, frage: string): Promise<{ ok: true }> {
    return this.json("POST", `/v1/anfragen/${encodeURIComponent(id)}/trennen`, { frage });
  }

  async vergessen(id: string): Promise<void> {
    await this.senden("DELETE", `/v1/anfragen/${encodeURIComponent(id)}`);
  }

  anhangSetzen(id: string, art: string, daten: Uint8Array): Promise<{ art: string; groesse: number }> {
    const pfad = `/v1/anfragen/${encodeURIComponent(id)}/anhaenge/${encodeURIComponent(art)}`;
    return this.json("PUT", pfad, daten);
  }

  async anhangLesen(id: string, art: string): Promise<AnhangBytes> {
    const pfad = `/v1/anfragen/${encodeURIComponent(id)}/anhaenge/${encodeURIComponent(art)}`;
    const antwort = await this.senden("GET", pfad);
    const roh = await antwort.arrayBuffer();
    return {
      medientyp: antwort.headers.get("content-type") ?? "application/octet-stream",
      daten: new Uint8Array(roh),
    };
  }

  private json<T>(methode: string, pfad: string, koerper?: object | Uint8Array): Promise<T> {
    return this.senden(methode, pfad, koerper).then(async (antwort) => {
      if (antwort.status === 204) {
        return undefined as T;
      }
      return (await antwort.json()) as T;
    });
  }

  private async senden(methode: string, pfad: string, koerper?: object | Uint8Array): Promise<AbrufAntwort> {
    const koepfe: Record<string, string> = {};
    if (this.zugang !== null) {
      koepfe.Authorization = `Bearer ${this.zugang}`;
    }
    let inhalt: string | Uint8Array | undefined;
    if (koerper instanceof Uint8Array) {
      inhalt = koerper;
    } else if (koerper !== undefined) {
      koepfe["Content-Type"] = "application/json";
      inhalt = JSON.stringify(koerper);
    }
    const init: AbrufInit = { method: methode, headers: koepfe };
    if (inhalt !== undefined) {
      init.body = inhalt;
    }
    const antwort = await fetch(this.basis + pfad, init);
    if (!antwort.ok) {
      throw await fehlerAus(antwort);
    }
    return antwort;
  }
}

async function fehlerAus(antwort: AbrufAntwort): Promise<MiniKiFehler> {
  let meldung = `Mini-KI antwortet mit Status ${antwort.status}.`;
  const typ = antwort.headers.get("content-type") ?? "";
  if (typ.includes("application/json")) {
    try {
      const daten = await antwort.json();
      if (istObjekt(daten) && typeof daten.fehler === "string" && daten.fehler !== "") {
        meldung = daten.fehler;
      }
    } catch {
      /* Der Fehlertext oben bleibt. */
    }
  }
  return new MiniKiFehler(antwort.status, meldung);
}

function istObjekt(wert: unknown): wert is Record<string, unknown> {
  return typeof wert === "object" && wert !== null;
}
