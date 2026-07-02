/**
 * Mock File API for testing file uploads.
 *
 * Provides a minimal File implementation compatible with JSDOM test environments,
 * supporting text/ArrayBuffer reading and blob slicing.
 */
export class MockFile {
  fileBits: BlobPart[];
  name: string;
  lastModified: number;
  size: number;
  type: string;
  webkitRelativePath: string;

  constructor(fileBits: BlobPart[], name: string, options?: FilePropertyBag) {
    this.fileBits = fileBits;
    this.name = name;
    this.lastModified = Date.now();
    this.size = 0;
    this.type = options?.type ?? '';
    this.webkitRelativePath = '';
  }

  text(): Promise<string> {
    return Promise.resolve(
      typeof this.fileBits[0] === 'string' ? this.fileBits[0] : JSON.stringify(this.fileBits[0]),
    );
  }

  arrayBuffer(): Promise<ArrayBuffer> {
    return Promise.resolve(new ArrayBuffer(0));
  }

  slice(): Blob {
    return new Blob();
  }

  stream(): ReadableStream {
    return new ReadableStream();
  }

  bytes(): Promise<Uint8Array> {
    return Promise.resolve(new Uint8Array());
  }
}
