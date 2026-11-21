/**
 * Regroupe les blocs Int16 du module (128 échantillons) en paquets thc.audio-stream.v1 :
 * [seq : uint32 LE][échantillons Int16 LE]. Concaténation + redécoupage, sans aucune modification.
 */

export const PACKET_FRAMES = 2400; // 50 ms à 48 kHz
const SEQ_BYTES = 4;

/** Les Int16Array sont copiés tels quels : la plateforme doit être little-endian. */
export function isLittleEndian(): boolean {
  return new Uint8Array(Uint16Array.of(1).buffer)[0] === 1;
}

export function encodePacket(seq: number, samples: Int16Array): ArrayBuffer {
  const buffer = new ArrayBuffer(SEQ_BYTES + samples.byteLength);
  new DataView(buffer).setUint32(0, seq, true);
  new Int16Array(buffer, SEQ_BYTES).set(samples);
  return buffer;
}

export class Packetizer {
  private readonly pending = new Int16Array(PACKET_FRAMES);
  private filled = 0;
  private seq = 0;
  framesSent = 0;

  constructor(private readonly send: (packet: ArrayBuffer) => void) {}

  get packetsSent(): number {
    return this.seq;
  }

  push(block: Int16Array): void {
    let offset = 0;
    while (offset < block.length) {
      const take = Math.min(PACKET_FRAMES - this.filled, block.length - offset);
      this.pending.set(block.subarray(offset, offset + take), this.filled);
      this.filled += take;
      offset += take;
      if (this.filled === PACKET_FRAMES) this.emit();
    }
  }

  /** Vide le dernier paquet (plus court) à l'arrêt de la capture. */
  flush(): void {
    if (this.filled > 0) this.emit();
  }

  private emit(): void {
    this.send(encodePacket(this.seq, this.pending.subarray(0, this.filled)));
    this.seq += 1;
    this.framesSent += this.filled;
    this.filled = 0;
  }
}
