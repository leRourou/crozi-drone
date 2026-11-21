import { describe, expect, it } from "vitest";
import { encodePacket, isLittleEndian, PACKET_FRAMES, Packetizer } from "./packetizer";

function blocks(count: number, size = 128): Int16Array[] {
  let next = -32768;
  return Array.from({ length: count }, () =>
    Int16Array.from({ length: size }, () => {
      const value = next;
      next = next === 32767 ? -32768 : next + 7919 > 32767 ? next + 7919 - 65536 : next + 7919;
      return value;
    }),
  );
}

function concat(parts: Int16Array[]): Int16Array {
  const out = new Int16Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function decode(packet: ArrayBuffer): { seq: number; samples: Int16Array } {
  const view = new DataView(packet);
  const samples = new Int16Array((packet.byteLength - 4) / 2);
  for (let i = 0; i < samples.length; i += 1) samples[i] = view.getInt16(4 + 2 * i, true);
  return { seq: view.getUint32(0, true), samples };
}

describe("encodePacket", () => {
  it("writes seq as uint32 little-endian followed by the samples", () => {
    const bytes = new Uint8Array(encodePacket(0x01020304, Int16Array.of(1, -2)));
    expect([...bytes]).toEqual([0x04, 0x03, 0x02, 0x01, 0x01, 0x00, 0xfe, 0xff]);
  });

  it("encodes the largest seq without overflow", () => {
    expect(decode(encodePacket(0xffffffff, Int16Array.of(0))).seq).toBe(0xffffffff);
  });
});

describe("Packetizer", () => {
  it("splits 128-sample blocks into 2400-sample packets without loss or reordering", () => {
    const packets: ArrayBuffer[] = [];
    const packetizer = new Packetizer((p) => packets.push(p));
    const input = blocks(100); // 12 800 échantillons : 5 paquets pleins + 800 restants
    input.forEach((block) => packetizer.push(block));
    packetizer.flush();

    const decoded = packets.map(decode);
    expect(decoded.map((p) => p.seq)).toEqual([0, 1, 2, 3, 4, 5]);
    expect(decoded.slice(0, -1).every((p) => p.samples.length === PACKET_FRAMES)).toBe(true);
    expect(decoded.at(-1)?.samples.length).toBe(800);
    expect(concat(decoded.map((p) => p.samples))).toEqual(concat(input));
    expect(packetizer.framesSent).toBe(12_800);
    expect(packetizer.packetsSent).toBe(6);
  });

  it("handles blocks larger than a packet and odd sizes", () => {
    const packets: ArrayBuffer[] = [];
    const packetizer = new Packetizer((p) => packets.push(p));
    const input = [...blocks(1, 5000), ...blocks(3, 77)];
    input.forEach((block) => packetizer.push(block));
    packetizer.flush();
    expect(packets.map((p) => decode(p).samples.length)).toEqual([2400, 2400, 431]);
    expect(concat(packets.map((p) => decode(p).samples))).toEqual(concat(input));
  });

  it("flush with an empty buffer sends nothing", () => {
    const packets: ArrayBuffer[] = [];
    const packetizer = new Packetizer((p) => packets.push(p));
    packetizer.push(new Int16Array(PACKET_FRAMES));
    packetizer.flush();
    packetizer.flush();
    expect(packets).toHaveLength(1);
  });

  it("does not keep a reference to the caller's block", () => {
    const packets: ArrayBuffer[] = [];
    const packetizer = new Packetizer((p) => packets.push(p));
    const block = Int16Array.of(1, 2, 3);
    packetizer.push(block);
    block.fill(9);
    packetizer.flush();
    expect([...decode(packets[0]).samples]).toEqual([1, 2, 3]);
  });
});

describe("Packetizer flush", () => {
  it("sends a final packet holding a single sample", () => {
    const packets: ArrayBuffer[] = [];
    const packetizer = new Packetizer((p) => packets.push(p));
    packetizer.push(Int16Array.of(-7));
    packetizer.flush();
    expect(packets.map((p) => [...decode(p).samples])).toEqual([[-7]]);
  });
});

describe("isLittleEndian", () => {
  it("is true on the test machine (x86/ARM)", () => {
    expect(isLittleEndian()).toBe(true);
  });
});
