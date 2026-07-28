# Pure Python implementation of Monocypher cryptographic library

import hashlib
import struct

# Helper utilities
def load32_le(s, offset=0):
    return s[offset] | (s[offset+1] << 8) | (s[offset+2] << 16) | (s[offset+3] << 24)

def load64_le(s, offset=0):
    return load32_le(s, offset) | (load32_le(s, offset+4) << 32)

def load24_le(s, offset=0):
    return s[offset] | (s[offset+1] << 8) | (s[offset+2] << 16)

def load64_be(s, offset=0):
    return struct.unpack_from('>Q', s, offset)[0]

def store32_le(in_val):
    in_val &= 0xffffffff
    return bytes([in_val & 0xff, (in_val >> 8) & 0xff, (in_val >> 16) & 0xff, (in_val >> 24) & 0xff])

def store32_le_into(buf, offset, in_val):
    in_val &= 0xffffffff
    buf[offset] = in_val & 0xff
    buf[offset+1] = (in_val >> 8) & 0xff
    buf[offset+2] = (in_val >> 16) & 0xff
    buf[offset+3] = (in_val >> 24) & 0xff

def store64_le(in_val):
    in_val &= 0xffffffffffffffff
    return store32_le(in_val & 0xffffffff) + store32_le(in_val >> 32)

def store64_be(in_val):
    return struct.pack('>Q', in_val & 0xffffffffffffffff)

def rotr64(x, n):
    x &= 0xffffffffffffffff
    return ((x >> n) | (x << (64 - n))) & 0xffffffffffffffff

def rotl32(x, n):
    x &= 0xffffffff
    return ((x << n) | (x >> (32 - n))) & 0xffffffff

def crypto_verify16(a, b):
    diff = 0
    for i in range(16):
        diff |= a[i] ^ b[i]
    return 0 if diff == 0 else -1

def crypto_verify32(a, b):
    diff = 0
    for i in range(32):
        diff |= a[i] ^ b[i]
    return 0 if diff == 0 else -1

def crypto_verify64(a, b):
    diff = 0
    for i in range(64):
        diff |= a[i] ^ b[i]
    return 0 if diff == 0 else -1

def crypto_wipe(buf):
    if isinstance(buf, bytearray):
        for i in range(len(buf)):
            buf[i] = 0

# --- ChaCha20 ---
CHACHA_CONST = b"expand 32-byte k"

def chacha20_quarterround(state, a, b, c, d):
    state[a] = (state[a] + state[b]) & 0xffffffff
    state[d] = rotl32(state[d] ^ state[a], 16)
    state[c] = (state[c] + state[d]) & 0xffffffff
    state[b] = rotl32(state[b] ^ state[c], 12)
    state[a] = (state[a] + state[b]) & 0xffffffff
    state[d] = rotl32(state[d] ^ state[a], 8)
    state[c] = (state[c] + state[d]) & 0xffffffff
    state[b] = rotl32(state[b] ^ state[c], 7)

def chacha20_rounds(out, inp):
    t = list(inp)
    for _ in range(10):
        chacha20_quarterround(t, 0, 4, 8, 12)
        chacha20_quarterround(t, 1, 5, 9, 13)
        chacha20_quarterround(t, 2, 6, 10, 14)
        chacha20_quarterround(t, 3, 7, 11, 15)
        chacha20_quarterround(t, 0, 5, 10, 15)
        chacha20_quarterround(t, 1, 6, 11, 12)
        chacha20_quarterround(t, 2, 7, 8, 13)
        chacha20_quarterround(t, 3, 4, 9, 14)
    for i in range(16):
        out[i] = t[i]

def crypto_chacha20_h(out, key, in_buf):
    block = [0] * 16
    for i in range(4):
        block[i] = load32_le(CHACHA_CONST, i * 4)
    for i in range(8):
        block[4 + i] = load32_le(key, i * 4)
    for i in range(4):
        block[12 + i] = load32_le(in_buf, i * 4)
    
    chacha20_rounds(block, block)
    
    for i in range(4):
        store32_le_into(out, i * 4, block[i])
        store32_le_into(out, 16 + i * 4, block[12 + i])

def crypto_chacha20_djb(cipher_text, plain_text, text_size, key, nonce, ctr):
    inp = [0] * 16
    for i in range(4):
        inp[i] = load32_le(CHACHA_CONST, i * 4)
    for i in range(8):
        inp[4 + i] = load32_le(key, i * 4)
    inp[14] = load32_le(nonce, 0)
    inp[15] = load32_le(nonce, 4)
    inp[12] = ctr & 0xffffffff
    inp[13] = (ctr >> 32) & 0xffffffff

    pool = [0] * 16
    nb_blocks = text_size >> 6
    offset = 0

    for _ in range(nb_blocks):
        chacha20_rounds(pool, inp)
        if plain_text is not None:
            for j in range(16):
                p = (pool[j] + inp[j]) & 0xffffffff
                pt_val = load32_le(plain_text, offset + j * 4)
                store32_le_into(cipher_text, offset + j * 4, p ^ pt_val)
        else:
            for j in range(16):
                p = (pool[j] + inp[j]) & 0xffffffff
                store32_le_into(cipher_text, offset + j * 4, p)
        offset += 64
        inp[12] = (inp[12] + 1) & 0xffffffff
        if inp[12] == 0:
            inp[13] = (inp[13] + 1) & 0xffffffff

    rem_size = text_size & 63
    if rem_size > 0:
        chacha20_rounds(pool, inp)
        tmp = bytearray(64)
        for i in range(16):
            store32_le_into(tmp, i * 4, (pool[i] + inp[i]) & 0xffffffff)
        for i in range(rem_size):
            pt_byte = plain_text[offset + i] if plain_text is not None else 0
            cipher_text[offset + i] = tmp[i] ^ pt_byte
        inp[12] = (inp[12] + 1) & 0xffffffff
        if inp[12] == 0:
            inp[13] = (inp[13] + 1) & 0xffffffff

    new_ctr = inp[12] | (inp[13] << 32)
    return new_ctr

def crypto_chacha20_ietf(cipher_text, plain_text, text_size, key, nonce, ctr):
    big_ctr = ctr + (load32_le(nonce, 0) << 32)
    new_ctr = crypto_chacha20_djb(cipher_text, plain_text, text_size, key, nonce[4:12], big_ctr)
    return new_ctr & 0xffffffff

def crypto_chacha20_x(cipher_text, plain_text, text_size, key, nonce, ctr):
    sub_key = bytearray(32)
    crypto_chacha20_h(sub_key, key, nonce[:16])
    return crypto_chacha20_djb(cipher_text, plain_text, text_size, sub_key, nonce[16:24], ctr)


# --- Poly1305 ---
class Poly1305Ctx:
    def __init__(self):
        self.c = bytearray(16)
        self.c_idx = 0
        self.r = [0] * 4
        self.pad = [0] * 4
        self.h = [0] * 5

def poly_blocks(ctx, in_buf, offset, nb_blocks, end):
    r0, r1, r2, r3 = ctx.r
    rr0 = (r0 >> 2) * 5
    rr1 = (r1 >> 2) + r1
    rr2 = (r2 >> 2) + r2
    rr3 = (r3 >> 2) + r3
    rr4 = r0 & 3
    h0, h1, h2, h3, h4 = ctx.h

    for _ in range(nb_blocks):
        s0 = h0 + load32_le(in_buf, offset); offset += 4
        s1 = h1 + load32_le(in_buf, offset); offset += 4
        s2 = h2 + load32_le(in_buf, offset); offset += 4
        s3 = h3 + load32_le(in_buf, offset); offset += 4
        s4 = h4 + end

        x0 = s0*r0 + s1*rr3 + s2*rr2 + s3*rr1 + s4*rr0
        x1 = s0*r1 + s1*r0  + s2*rr3 + s3*rr2 + s4*rr1
        x2 = s0*r2 + s1*r1  + s2*r0  + s3*rr3 + s4*rr2
        x3 = s0*r3 + s1*r2  + s2*r1  + s3*r0  + s4*rr3
        x4 = s4*rr4

        u5 = (x3 >> 32) + x4
        u0 = (u5 >> 2) * 5 + (x0 & 0xffffffff)
        u1 = (u0 >> 32) + (x1 & 0xffffffff) + (x0 >> 32)
        u2 = (u1 >> 32) + (x2 & 0xffffffff) + (x1 >> 32)
        u3 = (u2 >> 32) + (x3 & 0xffffffff) + (x2 >> 32)
        u4 = (u3 >> 32) + (u5 & 3)

        h0 = u0 & 0xffffffff
        h1 = u1 & 0xffffffff
        h2 = u2 & 0xffffffff
        h3 = u3 & 0xffffffff
        h4 = u4

    ctx.h = [h0, h1, h2, h3, h4]

def crypto_poly1305_init(ctx, key):
    ctx.h = [0] * 5
    ctx.c_idx = 0
    for i in range(4):
        ctx.r[i] = load32_le(key, i * 4)
        ctx.pad[i] = load32_le(key, 16 + i * 4)
    ctx.r[0] &= 0x0fffffff
    ctx.r[1] &= 0x0ffffffc
    ctx.r[2] &= 0x0ffffffc
    ctx.r[3] &= 0x0ffffffc

def crypto_poly1305_update(ctx, message, message_size):
    if message_size == 0:
        return
    
    offset = 0
    gap_val = (~ctx.c_idx + 1) & 15
    aligned = min(gap_val, message_size)
    for _ in range(aligned):
        ctx.c[ctx.c_idx] = message[offset]
        ctx.c_idx += 1
        offset += 1
        message_size -= 1

    if ctx.c_idx == 16:
        poly_blocks(ctx, ctx.c, 0, 1, 1)
        ctx.c_idx = 0

    nb_blocks = message_size >> 4
    if nb_blocks > 0:
        poly_blocks(ctx, message, offset, nb_blocks, 1)
        offset += nb_blocks << 4
        message_size &= 15

    for i in range(message_size):
        ctx.c[ctx.c_idx] = message[offset + i]
        ctx.c_idx += 1

def crypto_poly1305_final(ctx, mac):
    if ctx.c_idx != 0:
        for i in range(ctx.c_idx, 16):
            ctx.c[i] = 0
        ctx.c[ctx.c_idx] = 1
        poly_blocks(ctx, ctx.c, 0, 1, 0)

    c = 5
    for i in range(4):
        c += ctx.h[i]
        c >>= 32
    c += ctx.h[4]
    c = (c >> 2) * 5

    for i in range(4):
        c += ctx.h[i] + ctx.pad[i]
        store32_le_into(mac, i * 4, c & 0xffffffff)
        c >>= 32

def crypto_poly1305(mac, message, message_size, key):
    ctx = Poly1305Ctx()
    crypto_poly1305_init(ctx, key)
    crypto_poly1305_update(ctx, message, message_size)
    crypto_poly1305_final(ctx, mac)


# --- BLAKE2b ---
BLAKE2B_IV = [
    0x6a09e667f3bcc908, 0xbb67ae8584caa73b,
    0x3c6ef372fe94f82b, 0xa54ff53a5f1d36f1,
    0x510e527fade682d1, 0x9b05688c2b3e6c1f,
    0x1f83d9abfb41bd6b, 0x5be0cd19137e2179,
]

BLAKE2B_SIGMA = [
    [ 0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14, 15],
    [14, 10,  4,  8,  9, 15, 13,  6,  1, 12,  0,  2, 11,  7,  5,  3],
    [11,  8, 12,  0,  5,  2, 15, 13, 10, 14,  3,  6,  7,  1,  9,  4],
    [ 7,  9,  3,  1, 13, 12, 11, 14,  2,  6,  5, 10,  4,  0, 15,  8],
    [ 9,  0,  5,  7,  2,  4, 10, 15, 14,  1, 11, 12,  6,  8,  3, 13],
    [ 2, 12,  6, 10,  0, 11,  8,  3,  4, 13,  7,  5, 15, 14,  1,  9],
    [12,  5,  1, 15, 14, 13,  4, 10,  0,  7,  6,  3,  9,  2,  8, 11],
    [13, 11,  7, 14, 12,  1,  3,  9,  5,  0, 15,  4,  8,  6,  2, 10],
    [ 6, 15, 14,  9, 11,  3,  0,  8, 12,  2, 13,  7,  1,  4, 10,  5],
    [10,  2,  8,  4,  7,  6,  1,  5, 15, 11,  9, 14,  3, 12, 13,  0],
    [ 0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14, 15],
    [14, 10,  4,  8,  9, 15, 13,  6,  1, 12,  0,  2, 11,  7,  5,  3],
]

class Blake2bCtx:
    def __init__(self):
        self.hash = [0] * 8
        self.input_offset = [0, 0]
        self.input = [0] * 16
        self.input_idx = 0
        self.hash_size = 0

def blake2b_compress(ctx, is_last_block):
    y = ctx.input_idx
    ctx.input_offset[0] += y
    if ctx.input_offset[0] < y:
        ctx.input_offset[1] += 1

    v = [0] * 16
    for i in range(8):
        v[i] = ctx.hash[i]
        v[i+8] = BLAKE2B_IV[i]
    v[12] ^= ctx.input_offset[0]
    v[13] ^= ctx.input_offset[1]
    if is_last_block:
        v[14] ^= 0xffffffffffffffff
    
    inp = ctx.input

    def blake2_g(a, b, c, d, x, y_val):
        v[a] = (v[a] + v[b] + x) & 0xffffffffffffffff
        v[d] = rotr64(v[d] ^ v[a], 32)
        v[c] = (v[c] + v[d]) & 0xffffffffffffffff
        v[b] = rotr64(v[b] ^ v[c], 24)
        v[a] = (v[a] + v[b] + y_val) & 0xffffffffffffffff
        v[d] = rotr64(v[d] ^ v[a], 16)
        v[c] = (v[c] + v[d]) & 0xffffffffffffffff
        v[b] = rotr64(v[b] ^ v[c], 63)

    for i in range(12):
        sig = BLAKE2B_SIGMA[i]
        blake2_g(0, 4, 8, 12, inp[sig[0]], inp[sig[1]])
        blake2_g(1, 5, 9, 13, inp[sig[2]], inp[sig[3]])
        blake2_g(2, 6, 10, 14, inp[sig[4]], inp[sig[5]])
        blake2_g(3, 7, 11, 15, inp[sig[6]], inp[sig[7]])
        blake2_g(0, 5, 10, 15, inp[sig[8]], inp[sig[9]])
        blake2_g(1, 6, 11, 12, inp[sig[10]], inp[sig[11]])
        blake2_g(2, 7, 8, 13, inp[sig[12]], inp[sig[13]])
        blake2_g(3, 4, 9, 14, inp[sig[14]], inp[sig[15]])

    for i in range(8):
        ctx.hash[i] ^= v[i] ^ v[i+8]

def crypto_blake2b_keyed_init(ctx, hash_size, key, key_size):
    for i in range(8):
        ctx.hash[i] = BLAKE2B_IV[i]
    ctx.hash[0] ^= 0x01010000 ^ (key_size << 8) ^ hash_size
    ctx.input_offset = [0, 0]
    ctx.hash_size = hash_size
    ctx.input_idx = 0
    ctx.input = [0] * 16

    if key_size > 0:
        key_block = bytearray(128)
        key_block[:key_size] = key[:key_size]
        for i in range(16):
            ctx.input[i] = load64_le(key_block, i * 8)
        ctx.input_idx = 128

def crypto_blake2b_init(ctx, hash_size):
    crypto_blake2b_keyed_init(ctx, hash_size, None, 0)

def crypto_blake2b_update(ctx, message, message_size):
    if message_size == 0:
        return
    
    offset = 0

    if (ctx.input_idx & 7) != 0:
        gap_val = (~ctx.input_idx + 1) & 7
        nb_bytes = min(gap_val, message_size)
        word = ctx.input_idx >> 3
        byte_pos = ctx.input_idx & 7
        for i in range(nb_bytes):
            ctx.input[word] |= message[offset + i] << ((byte_pos + i) << 3)
        ctx.input_idx += nb_bytes
        offset += nb_bytes
        message_size -= nb_bytes

    if (ctx.input_idx & 127) != 0:
        gap_val = (~ctx.input_idx + 1) & 127
        nb_words = min(gap_val, message_size) >> 3
        for i in range(nb_words):
            ctx.input[(ctx.input_idx >> 3) + i] = load64_le(message, offset + i * 8)
        ctx.input_idx += nb_words << 3
        offset += nb_words << 3
        message_size -= nb_words << 3

    nb_blocks = message_size >> 7
    for _ in range(nb_blocks):
        if ctx.input_idx == 128:
            blake2b_compress(ctx, 0)
        for i in range(16):
            ctx.input[i] = load64_le(message, offset + i * 8)
        offset += 128
        ctx.input_idx = 128
    message_size &= 127

    if message_size != 0:
        if ctx.input_idx == 128:
            blake2b_compress(ctx, 0)
            ctx.input_idx = 0
        if ctx.input_idx == 0:
            ctx.input = [0] * 16

        nb_words = message_size >> 3
        for i in range(nb_words):
            ctx.input[i] = load64_le(message, offset + i * 8)
        ctx.input_idx += nb_words << 3
        offset += nb_words << 3
        message_size -= nb_words << 3

        for i in range(message_size):
            word = ctx.input_idx >> 3
            byte_pos = ctx.input_idx & 7
            ctx.input[word] |= message[offset + i] << (byte_pos << 3)
            ctx.input_idx += 1

def crypto_blake2b_final(ctx, hash_out):
    blake2b_compress(ctx, 1)
    hash_size = min(ctx.hash_size, 64)
    nb_words = hash_size >> 3
    for i in range(nb_words):
        store32_le_into(hash_out, i * 8, ctx.hash[i] & 0xffffffff)
        store32_le_into(hash_out, i * 8 + 4, (ctx.hash[i] >> 32) & 0xffffffff)
    for i in range(nb_words << 3, hash_size):
        hash_out[i] = (ctx.hash[i >> 3] >> (8 * (i & 7))) & 0xff

def crypto_blake2b_keyed(hash_out, hash_size, key, key_size, message, message_size):
    ctx = Blake2bCtx()
    crypto_blake2b_keyed_init(ctx, hash_size, key, key_size)
    crypto_blake2b_update(ctx, message, message_size)
    crypto_blake2b_final(ctx, hash_out)

def crypto_blake2b(hash_out, hash_size, message, message_size):
    crypto_blake2b_keyed(hash_out, hash_size, None, 0, message, message_size)


# --- SHA-512 ---
class Sha512Ctx:
    def __init__(self):
        self.h = hashlib.sha512()

def crypto_sha512_init(ctx):
    ctx.h = hashlib.sha512()

def crypto_sha512_update(ctx, message, message_size):
    if message_size > 0 and message is not None:
        ctx.h.update(message[:message_size])

def crypto_sha512_final(ctx, hash_out):
    hash_out[:64] = ctx.h.digest()

def crypto_sha512(hash_out, message, message_size):
    if message_size > 0 and message is not None:
        hash_out[:64] = hashlib.sha512(message[:message_size]).digest()
    else:
        hash_out[:64] = hashlib.sha512(b"").digest()

class Sha512HmacCtx:
    def __init__(self):
        self.key = bytearray(128)
        self.ctx = Sha512Ctx()

def crypto_sha512_hmac_init(ctx, key, key_size):
    real_key = key
    if key_size > 128:
        real_key = bytearray(64)
        crypto_sha512(real_key, key, key_size)
        key_size = 64

    for i in range(key_size):
        ctx.key[i] = real_key[i] ^ 0x36
    for i in range(key_size, 128):
        ctx.key[i] = 0x36

    crypto_sha512_init(ctx.ctx)
    crypto_sha512_update(ctx.ctx, ctx.key, 128)

def crypto_sha512_hmac_update(ctx, message, message_size):
    crypto_sha512_update(ctx.ctx, message, message_size)

def crypto_sha512_hmac_final(ctx, hmac_out):
    crypto_sha512_final(ctx.ctx, hmac_out)
    for i in range(128):
        ctx.key[i] ^= 0x36 ^ 0x5c
    crypto_sha512_init(ctx.ctx)
    crypto_sha512_update(ctx.ctx, ctx.key, 128)
    crypto_sha512_update(ctx.ctx, hmac_out, 64)
    crypto_sha512_final(ctx.ctx, hmac_out)

def crypto_sha512_hmac(hmac_out, key, key_size, message, message_size):
    ctx = Sha512HmacCtx()
    crypto_sha512_hmac_init(ctx, key, key_size)
    crypto_sha512_hmac_update(ctx, message, message_size)
    crypto_sha512_hmac_final(ctx, hmac_out)

def crypto_sha512_hkdf_expand(okm, okm_size, prk, prk_size, info, info_size):
    not_first = False
    ctr = 1
    blk = bytearray(64)
    offset = 0

    while okm_size > 0:
        out_size = min(okm_size, 64)
        ctx = Sha512HmacCtx()
        crypto_sha512_hmac_init(ctx, prk, prk_size)
        if not_first:
            crypto_sha512_hmac_update(ctx, blk, 64)
        crypto_sha512_hmac_update(ctx, info, info_size)
        crypto_sha512_hmac_update(ctx, bytes([ctr]), 1)
        crypto_sha512_hmac_final(ctx, blk)

        okm[offset : offset + out_size] = blk[:out_size]
        not_first = True
        offset += out_size
        okm_size -= out_size
        ctr += 1

def crypto_sha512_hkdf(okm, okm_size, ikm, ikm_size, salt, salt_size, info, info_size):
    prk = bytearray(64)
    crypto_sha512_hmac(prk, salt, salt_size, ikm, ikm_size)
    crypto_sha512_hkdf_expand(okm, okm_size, prk, 64, info, info_size)


# --- Argon2 ---
def extended_hash(digest, digest_size, inp, input_size):
    ctx = Blake2bCtx()
    crypto_blake2b_init(ctx, min(digest_size, 64))
    hdr = store32_le(digest_size)
    crypto_blake2b_update(ctx, hdr, 4)
    crypto_blake2b_update(ctx, inp, input_size)
    
    first_digest = bytearray(min(digest_size, 64))
    crypto_blake2b_final(ctx, first_digest)
    digest[:len(first_digest)] = first_digest

    if digest_size > 64:
        r = ((digest_size + 31) >> 5) - 2
        i = 1
        in_pos = 0
        out_pos = 32
        while i < r:
            tmp = bytearray(64)
            crypto_blake2b(tmp, 64, digest[in_pos : in_pos + 64], 64)
            digest[out_pos : out_pos + 64] = tmp
            i += 1
            in_pos += 32
            out_pos += 32
        rem = digest_size - (32 * r)
        tmp = bytearray(rem)
        crypto_blake2b(tmp, rem, digest[in_pos : in_pos + 64], 64)
        digest[out_pos : out_pos + rem] = tmp

def argon2_g_rounds(b_arr):
    def lsb(x):
        return x & 0xffffffff

    def argon2_g(a_idx, b_idx, c_idx, d_idx):
        va = b_arr[a_idx]; vb = b_arr[b_idx]; vc = b_arr[c_idx]; vd = b_arr[d_idx]
        va = (va + vb + 2 * lsb(va) * lsb(vb)) & 0xffffffffffffffff
        vd ^= va; vd = rotr64(vd, 32)
        vc = (vc + vd + 2 * lsb(vc) * lsb(vd)) & 0xffffffffffffffff
        vb ^= vc; vb = rotr64(vb, 24)
        va = (va + vb + 2 * lsb(va) * lsb(vb)) & 0xffffffffffffffff
        vd ^= va; vd = rotr64(vd, 16)
        vc = (vc + vd + 2 * lsb(vc) * lsb(vd)) & 0xffffffffffffffff
        vb ^= vc; vb = rotr64(vb, 63)
        b_arr[a_idx] = va; b_arr[b_idx] = vb; b_arr[c_idx] = vc; b_arr[d_idx] = vd

    def round_func(v0, v1, v2, v3, v4, v5, v6, v7, v8, v9, v10, v11, v12, v13, v14, v15):
        argon2_g(v0, v4, v8, v12)
        argon2_g(v1, v5, v9, v13)
        argon2_g(v2, v6, v10, v14)
        argon2_g(v3, v7, v11, v15)
        argon2_g(v0, v5, v10, v15)
        argon2_g(v1, v6, v11, v12)
        argon2_g(v2, v7, v8, v13)
        argon2_g(v3, v4, v9, v14)

    for i in range(0, 128, 16):
        round_func(i, i+1, i+2, i+3, i+4, i+5, i+6, i+7, i+8, i+9, i+10, i+11, i+12, i+13, i+14, i+15)
    for i in range(0, 16, 2):
        round_func(i, i+1, i+16, i+17, i+32, i+33, i+48, i+49, i+64, i+65, i+80, i+81, i+96, i+97, i+112, i+113)

def crypto_argon2(hash_out, hash_size, work_area, config, inputs, extras):
    nb_lanes = config['nb_lanes']
    nb_blocks_cfg = config['nb_blocks']
    nb_passes = config['nb_passes']
    algorithm = config['algorithm']

    segment_size = nb_blocks_cfg // nb_lanes // 4
    lane_size = segment_size * 4
    nb_blocks = lane_size * nb_lanes

    blocks = [[0] * 128 for _ in range(nb_blocks)]

    initial_hash = bytearray(72)
    ctx = Blake2bCtx()
    crypto_blake2b_init(ctx, 64)
    def blake_u32(val):
        crypto_blake2b_update(ctx, store32_le(val), 4)
    def blake_u32_buf(buf, size):
        blake_u32(size)
        if size > 0 and buf is not None:
            crypto_blake2b_update(ctx, buf, size)

    blake_u32(nb_lanes)
    blake_u32(hash_size)
    blake_u32(nb_blocks_cfg)
    blake_u32(nb_passes)
    blake_u32(0x13)
    blake_u32(algorithm)
    blake_u32_buf(inputs.get('pass'), inputs.get('pass_size', 0))
    blake_u32_buf(inputs.get('salt'), inputs.get('salt_size', 0))
    blake_u32_buf(extras.get('key'), extras.get('key_size', 0))
    blake_u32_buf(extras.get('ad'), extras.get('ad_size', 0))

    init_hash_64 = bytearray(64)
    crypto_blake2b_final(ctx, init_hash_64)
    initial_hash[:64] = init_hash_64

    hash_area = bytearray(1024)
    for l in range(nb_lanes):
        for i in range(2):
            store32_le_into(initial_hash, 64, i)
            store32_le_into(initial_hash, 68, l)
            extended_hash(hash_area, 1024, initial_hash, 72)
            blk_arr = blocks[l * lane_size + i]
            for k in range(128):
                blk_arr[k] = load64_le(hash_area, k * 8)

    constant_time = (algorithm != 0) # 0 is ARGON2_D

    tmp = [0] * 128
    index_block = [0] * 128

    for pass_idx in range(nb_passes):
        for slice_idx in range(4):
            pass_offset = 2 if (pass_idx == 0 and slice_idx == 0) else 0
            slice_offset = slice_idx * segment_size

            if slice_idx == 2 and algorithm == 2: # ARGON2_ID
                constant_time = False

            for segment in range(nb_lanes):
                index_ctr = 1
                for block_idx in range(pass_offset, segment_size):
                    lane_offset = segment * lane_size
                    current_idx = lane_offset + slice_offset + block_idx
                    if block_idx == 0 and slice_offset == 0:
                        prev_idx = lane_offset + lane_size - 1
                    else:
                        prev_idx = current_idx - 1

                    if constant_time:
                        if block_idx == pass_offset or (block_idx % 128) == 0:
                            index_block = [0] * 128
                            index_block[0] = pass_idx
                            index_block[1] = segment
                            index_block[2] = slice_idx
                            index_block[3] = nb_blocks
                            index_block[4] = nb_passes
                            index_block[5] = algorithm
                            index_block[6] = index_ctr
                            index_ctr += 1

                            tmp = list(index_block)
                            argon2_g_rounds(index_block)
                            for k in range(128): index_block[k] ^= tmp[k]
                            tmp = list(index_block)
                            argon2_g_rounds(index_block)
                            for k in range(128): index_block[k] ^= tmp[k]

                        index_seed = index_block[block_idx % 128]
                    else:
                        index_seed = blocks[prev_idx][0]

                    next_slice = ((slice_idx + 1) % 4) * segment_size
                    window_start = 0 if pass_idx == 0 else next_slice
                    nb_segments = slice_idx if pass_idx == 0 else 3
                    if pass_idx == 0 and slice_idx == 0:
                        lane = segment
                    else:
                        lane = (index_seed >> 32) % nb_lanes

                    if lane == segment:
                        w_sub = block_idx - 1
                    elif block_idx == 0:
                        w_sub = -1 & 0xffffffff
                    else:
                        w_sub = 0
                    window_size = nb_segments * segment_size + w_sub

                    j1 = index_seed & 0xffffffff
                    x_val = (j1 * j1) >> 32
                    y_val = (window_size * x_val) >> 32
                    z_val = (window_size - 1) - y_val
                    ref = (window_start + z_val) % lane_size
                    ref_idx = lane * lane_size + ref

                    previous = blocks[prev_idx]
                    reference = blocks[ref_idx]
                    current = blocks[current_idx]

                    for k in range(128):
                        tmp[k] = previous[k] ^ reference[k]

                    if pass_idx == 0:
                        for k in range(128): current[k] = tmp[k]
                    else:
                        for k in range(128): current[k] ^= tmp[k]

                    argon2_g_rounds(tmp)
                    for k in range(128): current[k] ^= tmp[k]

    last_block = blocks[lane_size - 1]
    for lane in range(1, nb_lanes):
        next_block = blocks[lane * lane_size + lane_size - 1]
        for k in range(128):
            next_block[k] ^= last_block[k]
        last_block = next_block

    final_block = bytearray(1024)
    for k in range(128):
        store32_le_into(final_block, k * 8, last_block[k] & 0xffffffff)
        store32_le_into(final_block, k * 8 + 4, (last_block[k] >> 32) & 0xffffffff)

    extended_hash(hash_out, hash_size, final_block, 1024)


# --- Curve25519 & Ed25519 Math (Field & Group Arithmetic) ---
FE_SQRT_MINUS_1 = [
    -32595792, -7943725, 9377950, 3500415, 12389472,
    -272473, -25146209, -2005654, 326686, 11406482,
]
FE_D = [
    -10913610, 13857413, -15372611, 6949391, 114729,
    -8787816, -6275908, -3247719, -18696448, -12055116,
]
FE_D2 = [
    -21827239, -5839606, -30745221, 13898782, 229458,
    15978800, -12551817, -6495438, 29715968, 9444199,
]
FE_LOP_X = [
    21352778, 5345713, 4660180, -8347857, 24143090,
    14568123, 30185756, -12247770, -33528939, 8345319,
]
FE_LOP_Y = [
    -6952922, -1265500, 6862341, -7057498, -4037696,
    -5447722, 31680899, -15325402, -19365852, 1569102,
]
FE_UFACTOR = [
    -1917299, 15887451, -18755900, -7000830, -24778944,
    544946, -16816446, 4011309, -653372, 10741468,
]
FE_A2 = [12721188, 3529, 0, 0, 0, 0, 0, 0, 0, 0]
FE_A = [486662, 0, 0, 0, 0, 0, 0, 0, 0, 0]
FE_ONE = [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]

def fe_copy(f): return list(f)
def fe_0(): return [0] * 10
def fe_1(): return [1] + [0] * 9

def fe_neg(f):
    return [-x for x in f]

def fe_add(f, g):
    return [f[i] + g[i] for i in range(10)]

def fe_sub(f, g):
    return [f[i] - g[i] for i in range(10)]

def fe_cswap(f, g, b):
    mask = -b
    for i in range(10):
        x = (f[i] ^ g[i]) & mask
        f[i] ^= x
        g[i] ^= x

def fe_ccopy(f, g, b):
    mask = -b
    for i in range(10):
        x = (f[i] ^ g[i]) & mask
        f[i] ^= x

def fe_carry(t):
    t0, t1, t2, t3, t4, t5, t6, t7, t8, t9 = t
    c = (t0 + (1 << 25)) >> 26; t0 -= c * (1 << 26); t1 += c
    c = (t4 + (1 << 25)) >> 26; t4 -= c * (1 << 26); t5 += c
    c = (t1 + (1 << 24)) >> 25; t1 -= c * (1 << 25); t2 += c
    c = (t5 + (1 << 24)) >> 25; t5 -= c * (1 << 25); t6 += c
    c = (t2 + (1 << 25)) >> 26; t2 -= c * (1 << 26); t3 += c
    c = (t6 + (1 << 25)) >> 26; t6 -= c * (1 << 26); t7 += c
    c = (t3 + (1 << 24)) >> 25; t3 -= c * (1 << 25); t4 += c
    c = (t7 + (1 << 24)) >> 25; t7 -= c * (1 << 25); t8 += c
    c = (t4 + (1 << 25)) >> 26; t4 -= c * (1 << 26); t5 += c
    c = (t8 + (1 << 25)) >> 26; t8 -= c * (1 << 26); t9 += c
    c = (t9 + (1 << 24)) >> 25; t9 -= c * (1 << 25); t0 += c * 19
    c = (t0 + (1 << 25)) >> 26; t0 -= c * (1 << 26); t1 += c
    return [t0, t1, t2, t3, t4, t5, t6, t7, t8, t9]

def fe_frombytes_mask(s, nb_mask):
    mask = (0xffffff >> nb_mask)
    t0 = load32_le(s, 0)
    t1 = load24_le(s, 4) << 6
    t2 = load24_le(s, 7) << 5
    t3 = load24_le(s, 10) << 3
    t4 = load24_le(s, 13) << 2
    t5 = load32_le(s, 16)
    t6 = load24_le(s, 20) << 7
    t7 = load24_le(s, 23) << 5
    t8 = load24_le(s, 26) << 4
    t9 = (load24_le(s, 29) & mask) << 2
    return fe_carry([t0, t1, t2, t3, t4, t5, t6, t7, t8, t9])

def fe_frombytes(s):
    return fe_frombytes_mask(s, 1)

def fe_tobytes(h):
    t = list(h)
    q = (19 * t[9] + (1 << 24)) >> 25
    for i in range(5):
        q += t[2*i]
        q >>= 26
        q += t[2*i+1]
        q >>= 25
    q *= 19
    for i in range(5):
        t[i*2] += q
        q = t[i*2] >> 26
        t[i*2] -= q * (1 << 26)
        t[i*2+1] += q
        q = t[i*2+1] >> 25
        t[i*2+1] -= q * (1 << 25)

    s_out = bytearray(32)
    store32_le_into(s_out, 0,  ((t[0] & 0xffffffff) >> 0)  | ((t[1] & 0xffffffff) << 26))
    store32_le_into(s_out, 4,  ((t[1] & 0xffffffff) >> 6)  | ((t[2] & 0xffffffff) << 19))
    store32_le_into(s_out, 8,  ((t[2] & 0xffffffff) >> 13) | ((t[3] & 0xffffffff) << 13))
    store32_le_into(s_out, 12, ((t[3] & 0xffffffff) >> 19) | ((t[4] & 0xffffffff) << 6))
    store32_le_into(s_out, 16, ((t[5] & 0xffffffff) >> 0)  | ((t[6] & 0xffffffff) << 25))
    store32_le_into(s_out, 20, ((t[6] & 0xffffffff) >> 7)  | ((t[7] & 0xffffffff) << 19))
    store32_le_into(s_out, 24, ((t[7] & 0xffffffff) >> 13) | ((t[8] & 0xffffffff) << 12))
    store32_le_into(s_out, 28, ((t[8] & 0xffffffff) >> 20) | ((t[9] & 0xffffffff) << 6))
    return bytes(s_out)

def fe_mul_small(f, g):
    t = [f[i] * g for i in range(10)]
    return fe_carry(t)

def fe_mul(f, g):
    f0, f1, f2, f3, f4, f5, f6, f7, f8, f9 = f
    g0, g1, g2, g3, g4, g5, g6, g7, g8, g9 = g
    F1 = f1*2; F3 = f3*2; F5 = f5*2; F7 = f7*2; F9 = f9*2
    G1 = g1*19; G2 = g2*19; G3 = g3*19; G4 = g4*19; G5 = g5*19; G6 = g6*19; G7 = g7*19; G8 = g8*19; G9 = g9*19

    t0 = f0*g0 + F1*G9 + f2*G8 + F3*G7 + f4*G6 + F5*G5 + f6*G4 + F7*G3 + f8*G2 + F9*G1
    t1 = f0*g1 + f1*g0 + f2*G9 + f3*G8 + f4*G7 + f5*G6 + f6*G5 + f7*G4 + f8*G3 + f9*G2
    t2 = f0*g2 + F1*g1 + f2*g0 + F3*G9 + f4*G8 + F5*G7 + f6*G6 + F7*G5 + f8*G4 + F9*G3
    t3 = f0*g3 + f1*g2 + f2*g1 + f3*g0 + f4*G9 + f5*G8 + f6*G7 + f7*G6 + f8*G5 + f9*G4
    t4 = f0*g4 + F1*g3 + f2*g2 + F3*g1 + f4*g0 + F5*G9 + f6*G8 + F7*G7 + f8*G6 + F9*G5
    t5 = f0*g5 + f1*g4 + f2*g3 + f3*g2 + f4*g1 + f5*g0 + f6*G9 + f7*G8 + f8*G7 + f9*G6
    t6 = f0*g6 + F1*g5 + f2*g4 + F3*g3 + f4*g2 + F5*g1 + f6*g0 + F7*G9 + f8*G8 + F9*G7
    t7 = f0*g7 + f1*g6 + f2*g5 + f3*g4 + f4*g3 + f5*g2 + f6*g1 + f7*g0 + f8*G9 + f9*G8
    t8 = f0*g8 + F1*g7 + f2*g6 + F3*g5 + f4*g4 + F5*g3 + f6*g2 + F7*g1 + f8*g0 + F9*G9
    t9 = f0*g9 + f1*g8 + f2*g7 + f3*g6 + f4*g5 + f5*g4 + f6*g3 + f7*g2 + f8*g1 + f9*g0

    return fe_carry([t0, t1, t2, t3, t4, t5, t6, t7, t8, t9])

def fe_sq(f):
    f0, f1, f2, f3, f4, f5, f6, f7, f8, f9 = f
    f0_2 = f0*2; f1_2 = f1*2; f2_2 = f2*2; f3_2 = f3*2
    f4_2 = f4*2; f5_2 = f5*2; f6_2 = f6*2; f7_2 = f7*2
    f5_38 = f5*38; f6_19 = f6*19; f7_38 = f7*38; f8_19 = f8*19; f9_38 = f9*38

    t0 = f0*f0 + f1_2*f9_38 + f2_2*f8_19 + f3_2*f7_38 + f4_2*f6_19 + f5*f5_38
    t1 = f0_2*f1 + f2*f9_38 + f3_2*f8_19 + f4*f7_38 + f5_2*f6_19
    t2 = f0_2*f2 + f1_2*f1 + f3_2*f9_38 + f4_2*f8_19 + f5_2*f7_38 + f6*f6_19
    t3 = f0_2*f3 + f1_2*f2 + f4*f9_38 + f5_2*f8_19 + f6*f7_38
    t4 = f0_2*f4 + f1_2*f3_2 + f2*f2 + f5_2*f9_38 + f6_2*f8_19 + f7*f7_38
    t5 = f0_2*f5 + f1_2*f4 + f2_2*f3 + f6*f9_38 + f7_2*f8_19
    t6 = f0_2*f6 + f1_2*f5_2 + f2_2*f4 + f3_2*f3 + f7_2*f9_38 + f8*f8_19
    t7 = f0_2*f7 + f1_2*f6 + f2_2*f5 + f3_2*f4 + f8*f9_38
    t8 = f0_2*f8 + f1_2*f7_2 + f2_2*f6 + f3_2*f5_2 + f4*f4 + f9*f9_38
    t9 = f0_2*f9 + f1_2*f8 + f2_2*f7 + f3_2*f6 + f4*f5_2

    return fe_carry([t0, t1, t2, t3, t4, t5, t6, t7, t8, t9])

def fe_isodd(f):
    s = fe_tobytes(f)
    return s[0] & 1

def fe_isequal(f, g):
    fs = fe_tobytes(f)
    gs = fe_tobytes(g)
    return 1 if fs == gs else 0

def invsqrt(x):
    t0 = fe_sq(x)
    t1 = fe_sq(t0); t1 = fe_sq(t1); t1 = fe_mul(x, t1)
    t0 = fe_mul(t0, t1)
    t0 = fe_sq(t0); t0 = fe_mul(t1, t0)
    t1 = fe_sq(t0)
    for _ in range(1, 5): t1 = fe_sq(t1)
    t0 = fe_mul(t1, t0)
    t1 = fe_sq(t0)
    for _ in range(1, 10): t1 = fe_sq(t1)
    t1 = fe_mul(t1, t0)
    t2 = fe_sq(t1)
    for _ in range(1, 20): t2 = fe_sq(t2)
    t1 = fe_mul(t2, t1)
    t1 = fe_sq(t1)
    for _ in range(1, 10): t1 = fe_sq(t1)
    t0 = fe_mul(t1, t0)
    t1 = fe_sq(t0)
    for _ in range(1, 50): t1 = fe_sq(t1)
    t1 = fe_mul(t1, t0)
    t2 = fe_sq(t1)
    for _ in range(1, 100): t2 = fe_sq(t2)
    t1 = fe_mul(t2, t1)
    t1 = fe_sq(t1)
    for _ in range(1, 50): t1 = fe_sq(t1)
    t0 = fe_mul(t1, t0)
    t0 = fe_sq(t0)
    for _ in range(1, 2): t0 = fe_sq(t0)
    t0 = fe_mul(t0, x)

    quartic = fe_sq(t0)
    quartic = fe_mul(quartic, x)

    z0 = fe_isequal(x, fe_0())
    p1 = fe_isequal(quartic, FE_ONE)
    m1 = fe_isequal(quartic, fe_neg(FE_ONE))
    ms = fe_isequal(quartic, fe_neg(FE_SQRT_MINUS_1))

    if not (m1 | ms):
        isr = t0
    else:
        isr = fe_mul(t0, FE_SQRT_MINUS_1)

    is_square = p1 | m1 | z0
    return isr, is_square

def fe_invert(x):
    tmp = fe_sq(x)
    isr, _ = invsqrt(tmp)
    tmp = fe_sq(isr)
    return fe_mul(tmp, x)

def crypto_eddsa_trim_scalar(out, in_buf):
    out[:32] = in_buf[:32]
    out[0] &= 248
    out[31] &= 127
    out[31] |= 64

def scalar_bit(s, i):
    if i < 0: return 0
    return (s[i >> 3] >> (i & 7)) & 1

def scalarmult(q, scalar, p_buf, nb_bits):
    x1 = fe_frombytes(p_buf)
    x2 = fe_1(); z2 = fe_0()
    x3 = fe_copy(x1); z3 = fe_1()
    swap = 0

    for pos in range(nb_bits - 1, -1, -1):
        b = scalar_bit(scalar, pos)
        swap ^= b
        fe_cswap(x2, x3, swap)
        fe_cswap(z2, z3, swap)
        swap = b

        t0 = fe_sub(x3, z3)
        t1 = fe_sub(x2, z2)
        x2_add = fe_add(x2, z2)
        z2_add = fe_add(x3, z3)
        z3_mul = fe_mul(t0, x2_add)
        z2_mul = fe_mul(z2_add, t1)
        t0_sq = fe_sq(t1)
        t1_sq = fe_sq(x2_add)
        x3 = fe_add(z3_mul, z2_mul)
        z2 = fe_sub(z3_mul, z2_mul)
        x2 = fe_mul(t1_sq, t0_sq)
        t1 = fe_sub(t1_sq, t0_sq)
        z2 = fe_sq(z2)
        z3 = fe_mul_small(t1, 121666)
        x3 = fe_sq(x3)
        t0 = fe_add(t0_sq, z3)
        z3 = fe_mul(x1, z2)
        z2 = fe_mul(t1, t0)

    fe_cswap(x2, x3, swap)
    fe_cswap(z2, z3, swap)

    z2_inv = fe_invert(z2)
    x2_final = fe_mul(x2, z2_inv)
    q[:32] = fe_tobytes(x2_final)

def crypto_x25519(raw_shared_secret, your_secret_key, their_public_key):
    e = bytearray(32)
    crypto_eddsa_trim_scalar(e, your_secret_key)
    scalarmult(raw_shared_secret, e, their_public_key, 255)

def crypto_x25519_public_key(public_key, secret_key):
    base_point = b"\x09" + b"\x00" * 31
    crypto_x25519(public_key, secret_key, base_point)

def crypto_x25519_to_eddsa(eddsa, x25519):
    t2 = fe_frombytes(x25519)
    t1 = fe_sub(t2, FE_ONE)
    t2 = fe_add(t2, FE_ONE)
    t2 = fe_invert(t2)
    t1 = fe_mul(t1, t2)
    eddsa[:32] = fe_tobytes(t1)

def crypto_eddsa_to_x25519(x25519, eddsa):
    t2 = fe_frombytes(eddsa)
    t1 = fe_add(FE_ONE, t2)
    t2 = fe_sub(FE_ONE, t2)
    t2 = fe_invert(t2)
    t1 = fe_mul(t1, t2)
    x25519[:32] = fe_tobytes(t1)


# --- Arithmetic Modulo L ---
L_LIMBS = [0x5cf5d3ed, 0x5812631a, 0xa2f79cd6, 0x14def9de, 0, 0, 0, 0x10000000]
L_INT = sum(L_LIMBS[i] << (32 * i) for i in range(8))

def mod_l(reduced, x_words):
    val = sum(x_words[i] << (32 * i) for i in range(16))
    val %= L_INT
    for i in range(8):
        store32_le_into(reduced, i * 4, (val >> (32 * i)) & 0xffffffff)

def crypto_eddsa_reduce(reduced, expanded):
    x_words = [load32_le(expanded, i * 4) for i in range(16)]
    mod_l(reduced, x_words)

def crypto_eddsa_mul_add(r, a, b, c):
    a_int = sum(load32_le(a, i * 4) << (32 * i) for i in range(8))
    b_int = sum(load32_le(b, i * 4) << (32 * i) for i in range(8))
    c_int = sum(load32_le(c, i * 4) << (32 * i) for i in range(8))
    res = (a_int * b_int + c_int) % L_INT
    for i in range(8):
        store32_le_into(r, i * 4, (res >> (32 * i)) & 0xffffffff)


# --- Ed25519 Group Operations ---
class Ge:
    def __init__(self, X=None, Y=None, Z=None, T=None):
        self.X = X if X else fe_0()
        self.Y = Y if Y else fe_1()
        self.Z = Z if Z else fe_1()
        self.T = T if T else fe_0()

class GeCached:
    def __init__(self):
        self.Yp = fe_0()
        self.Ym = fe_0()
        self.Z = fe_1()
        self.T2 = fe_0()

class GePrecomp:
    def __init__(self, Yp=None, Ym=None, T2=None):
        self.Yp = Yp if Yp else fe_0()
        self.Ym = Ym if Ym else fe_0()
        self.T2 = T2 if T2 else fe_0()

def ge_tobytes(h):
    recip = fe_invert(h.Z)
    x = fe_mul(h.X, recip)
    y = fe_mul(h.Y, recip)
    s = bytearray(fe_tobytes(y))
    s[31] ^= fe_isodd(x) << 7
    return bytes(s)

def ge_frombytes_neg_vartime(s):
    h = Ge()
    h.Y = fe_frombytes(s)
    h.Z = fe_1()
    t = fe_sq(h.Y)
    x = fe_mul(t, FE_D)
    t = fe_sub(t, h.Z)
    x = fe_add(x, h.Z)
    x = fe_mul(t, x)
    isr, is_square = invsqrt(x)
    if not is_square:
        return None, -1
    x = fe_mul(t, isr)
    sign = (s[31] >> 7) & 1
    if fe_isodd(x) == sign:
        x = fe_neg(x)
    h.X = x
    h.T = fe_mul(h.X, h.Y)
    return h, 0

def ge_cache(p):
    c = GeCached()
    c.Yp = fe_add(p.Y, p.X)
    c.Ym = fe_sub(p.Y, p.X)
    c.Z = fe_copy(p.Z)
    c.T2 = fe_mul(p.T, FE_D2)
    return c

def ge_add(p, q):
    a = fe_add(p.Y, p.X)
    b = fe_sub(p.Y, p.X)
    a = fe_mul(a, q.Yp)
    b = fe_mul(b, q.Ym)
    s_Y = fe_add(a, b)
    s_X = fe_sub(a, b)

    s_Z = fe_add(p.Z, p.Z)
    s_Z = fe_mul(s_Z, q.Z)
    s_T = fe_mul(p.T, q.T2)
    a_new = fe_add(s_Z, s_T)
    b_new = fe_sub(s_Z, s_T)

    s = Ge()
    s.T = fe_mul(s_X, s_Y)
    s.X = fe_mul(s_X, b_new)
    s.Y = fe_mul(s_Y, a_new)
    s.Z = fe_mul(a_new, b_new)
    return s

def ge_sub(p, q):
    neg = GeCached()
    neg.Ym = fe_copy(q.Yp)
    neg.Yp = fe_copy(q.Ym)
    neg.Z = fe_copy(q.Z)
    neg.T2 = fe_neg(q.T2)
    return ge_add(p, neg)

def ge_madd(p, q):
    a = fe_add(p.Y, p.X)
    b = fe_sub(p.Y, p.X)
    a = fe_mul(a, q.Yp)
    b = fe_mul(b, q.Ym)
    s_Y = fe_add(a, b)
    s_X = fe_sub(a, b)

    s_Z = fe_add(p.Z, p.Z)
    s_T = fe_mul(p.T, q.T2)
    a_new = fe_add(s_Z, s_T)
    b_new = fe_sub(s_Z, s_T)

    s = Ge()
    s.T = fe_mul(s_X, s_Y)
    s.X = fe_mul(s_X, b_new)
    s.Y = fe_mul(s_Y, a_new)
    s.Z = fe_mul(a_new, b_new)
    return s

def ge_msub(p, q):
    neg = GePrecomp()
    neg.Ym = fe_copy(q.Yp)
    neg.Yp = fe_copy(q.Ym)
    neg.T2 = fe_neg(q.T2)
    return ge_madd(p, neg)

def ge_double(p):
    q_X = fe_sq(p.X)
    q_Y = fe_sq(p.Y)
    q_Z = fe_sq(p.Z)
    q_Z = fe_mul_small(q_Z, 2)
    q_T = fe_add(p.X, p.Y)
    s_T = fe_sq(q_T)
    q_T = fe_add(q_Y, q_X)
    q_Y = fe_sub(q_Y, q_X)
    q_X = fe_sub(s_T, q_T)
    q_Z = fe_sub(q_Z, q_Y)

    s = Ge()
    s.X = fe_mul(q_X, q_Z)
    s.Y = fe_mul(q_T, q_Y)
    s.Z = fe_mul(q_Y, q_Z)
    s.T = fe_mul(q_X, q_T)
    return s

B_WINDOW = [
    GePrecomp(
        [25967493,-14356035,29566456,3660896,-12694345,4014787,27544626,-11754271,-6079156,2047605],
        [-12545711,934262,-2722910,3049990,-727428,9406986,12720692,5043384,19500929,-15469378],
        [-8738181,4489570,9688441,-14785194,10184609,-12363380,29287919,11864899,-24514362,-4438546]
    ),
    GePrecomp(
        [15636291,-9688557,24204773,-7912398,616977,-16685262,27787600,-14772189,28944400,-1550024],
        [16568933,4717097,-11556148,-1102322,15682896,-11807043,16354577,-11775962,7689662,11199574],
        [30464156,-5976125,-11779434,-15670865,23220365,15915852,7512774,10017326,-17749093,-9920357]
    ),
    GePrecomp(
        [10861363,11473154,27284546,1981175,-30064349,12577861,32867885,14515107,-15438304,10819380],
        [4708026,6336745,20377586,9066809,-11272109,6594696,-25653668,12483688,-12668491,5581306],
        [19563160,16186464,-29386857,4097519,10237984,-4348115,28542350,13850243,-23678021,-15815942]
    ),
    GePrecomp(
        [5153746,9909285,1723747,-2777874,30523605,5516873,19480852,5230134,-23952439,-15175766],
        [-30269007,-3463509,7665486,10083793,28475525,1649722,20654025,16520125,30598449,7715701],
        [28881845,14381568,9657904,3680757,-20181635,7843316,-31400660,1370708,29794553,-1409300]
    ),
    GePrecomp(
        [-22518993,-6692182,14201702,-8745502,-23510406,8844726,18474211,-1361450,-13062696,13821877],
        [-6455177,-7839871,3374702,-4740862,-27098617,-10571707,31655028,-7212327,18853322,-14220951],
        [4566830,-12963868,-28974889,-12240689,-7602672,-2830569,-8514358,-10431137,2207753,-3209784]
    ),
    GePrecomp(
        [-25154831,-4185821,29681144,7868801,-6854661,-9423865,-12437364,-663000,-31111463,-16132436],
        [25576264,-2703214,7349804,-11814844,16472782,9300885,3844789,15725684,171356,6466918],
        [23103977,13316479,9739013,-16149481,817875,-15038942,8965339,-14088058,-30714912,16193877]
    ),
    GePrecomp(
        [-33521811,3180713,-2394130,14003687,-16903474,-16270840,17238398,4729455,-18074513,9256800],
        [-25182317,-4174131,32336398,5036987,-21236817,11360617,22616405,9761698,-19827198,630305],
        [-13720693,2639453,-24237460,-7406481,9494427,-5774029,-6554551,-15960994,-2449256,-14291300]
    ),
    GePrecomp(
        [-3151181,-5046075,9282714,6866145,-31907062,-863023,-18940575,15033784,25105118,-7894876],
        [-24326370,15950226,-31801215,-14592823,-11662737,-5090925,1573892,-2625887,2198790,-15804619],
        [-3099351,10324967,-2241613,7453183,-5446979,-2735503,-13812022,-16236442,-32461234,-12290683]
    )
]

B_COMB_LOW = [
    GePrecomp([-6816601,-2324159,-22559413,124364,18015490,8373481,19993724,1979872,-18549925,9085059], [10306321,403248,14839893,9633706,8463310,-8354981,-14305673,14668847,26301366,2818560], [-22701500,-3210264,-13831292,-2927732,-16326337,-14016360,12940910,177905,12165515,-2397893]),
    GePrecomp([-12282262,-7022066,9920413,-3064358,-32147467,2927790,22392436,-14852487,2719975,16402117], [-7236961,-4729776,2685954,-6525055,-24242706,-15940211,-6238521,14082855,10047669,12228189], [-30495588,-12893761,-11161261,3539405,-11502464,16491580,-27286798,-15030530,-7272871,-15934455]),
    GePrecomp([17650926,582297,-860412,-187745,-12072900,-10683391,-20352381,15557840,-31072141,-5019061], [-6283632,-2259834,-4674247,-4598977,-4089240,12435688,-31278303,1060251,6256175,10480726], [-13871026,2026300,-21928428,-2741605,-2406664,-8034988,7355518,15733500,-23379862,7489131]),
    GePrecomp([6883359,695140,23196907,9644202,-33430614,11354760,-20134606,6388313,-8263585,-8491918], [-7716174,-13605463,-13646110,14757414,-19430591,-14967316,10359532,-11059670,-21935259,12082603], [-11253345,-15943946,10046784,5414629,24840771,8086951,-6694742,9868723,15842692,-16224787]),
    GePrecomp([9639399,11810955,-24007778,-9320054,3912937,-9856959,996125,-8727907,-8919186,-14097242], [7248867,14468564,25228636,-8795035,14346339,8224790,6388427,-7181107,6468218,-8720783], [15513115,15439095,7342322,-10157390,18005294,-7265713,2186239,4884640,10826567,7135781]),
    GePrecomp([-14204238,5297536,-5862318,-6004934,28095835,4236101,-14203318,1958636,-16816875,3837147], [-5511166,-13176782,-29588215,12339465,15325758,-15945770,-8813185,11075932,-19608050,-3776283], [11728032,9603156,-4637821,-5304487,-7827751,2724948,31236191,-16760175,-7268616,14799772]),
    GePrecomp([-28842672,4840636,-12047946,-9101456,-1445464,381905,-30977094,-16523389,1290540,12798615], [27246947,-10320914,14792098,-14518944,5302070,-8746152,-3403974,-4149637,-27061213,10749585], [25572375,-6270368,-15353037,16037944,1146292,32198,23487090,9585613,24714571,-1418265]),
    GePrecomp([19844825,282124,-17583147,11004019,-32004269,-2716035,6105106,-1711007,-21010044,14338445], [8027505,8191102,-18504907,-12335737,25173494,-5923905,15446145,7483684,-30440441,10009108], [-14134701,-4174411,10246585,-14677495,33553567,-14012935,23366126,15080531,-7969992,7663473])
]

B_COMB_HIGH = [
    GePrecomp([33055887,-4431773,-521787,6654165,951411,-6266464,-5158124,6995613,-5397442,-6985227], [4014062,6967095,-11977872,3960002,8001989,5130302,-2154812,-1899602,-31954493,-16173976], [16271757,-9212948,23792794,731486,-25808309,-3546396,6964344,-4767590,10976593,10050757]),
    GePrecomp([2533007,-4288439,-24467768,-12387405,-13450051,14542280,12876301,13893535,15067764,8594792], [20073501,-11623621,3165391,-13119866,13188608,-11540496,-10751437,-13482671,29588810,2197295], [-1084082,11831693,6031797,14062724,14748428,-8159962,-20721760,11742548,31368706,13161200]),
    GePrecomp([2050412,-6457589,15321215,5273360,25484180,124590,-18187548,-7097255,-6691621,-14604792], [9938196,2162889,-6158074,-1711248,4278932,-2598531,-22865792,-7168500,-24323168,11746309], [-22691768,-14268164,5965485,9383325,20443693,5854192,28250679,-1381811,-10837134,13717818]),
    GePrecomp([-8495530,16382250,9548884,-4971523,-4491811,-3902147,6182256,-12832479,26628081,10395408], [27329048,-15853735,7715764,8717446,-9215518,-14633480,28982250,-5668414,4227628,242148], [-13279943,-7986904,-7100016,8764468,-27276630,3096719,29678419,-9141299,3906709,11265498]),
    GePrecomp([11918285,15686328,-17757323,-11217300,-27548967,4853165,-27168827,6807359,6871949,-1075745], [-29002610,13984323,-27111812,-2713442,28107359,-13266203,6155126,15104658,3538727,-7513788], [14103158,11233913,-33165269,9279850,31014152,4335090,-1827936,4590951,13960841,12787712]),
    GePrecomp([1469134,-16738009,33411928,13942824,8092558,-8778224,-11165065,1437842,22521552,-2792954], [31352705,-4807352,-25327300,3962447,12541566,-9399651,-27425693,7964818,-23829869,5541287], [-25732021,-6864887,23848984,3039395,-9147354,6022816,-27421653,10590137,25309915,-1584678]),
    GePrecomp([-22951376,5048948,31139401,-190316,-19542447,-626310,-17486305,-16511925,-18851313,-12985140], [-9684890,14681754,30487568,7717771,-10829709,9630497,30290549,-10531496,-27798994,-13812825], [5827835,16097107,-24501327,12094619,7413972,11447087,28057551,-1793987,-14056981,4359312]),
    GePrecomp([26323183,2342588,-21887793,-1623758,-6062284,2107090,-28724907,9036464,-19618351,-13055189], [-29697200,14829398,-4596333,14220089,-30022969,2955645,12094100,-13693652,-5941445,7047569], [-3201977,14413268,-12058324,-16417589,-9035655,-7224648,9258160,1399236,30397584,-5684634])
]

class SlideCtx:
    def __init__(self):
        self.next_index = -1
        self.next_digit = -1
        self.next_check = 0

def slide_init(ctx, scalar):
    i = 252
    while i > 0 and scalar_bit(scalar, i) == 0:
        i -= 1
    ctx.next_check = i + 1
    ctx.next_index = -1
    ctx.next_digit = -1

def slide_step(ctx, width, i, scalar):
    if i == ctx.next_check:
        if scalar_bit(scalar, i) == scalar_bit(scalar, i - 1):
            ctx.next_check -= 1
        else:
            w = min(width, i + 1)
            v = -(scalar_bit(scalar, i) << (w - 1))
            for j in range(w - 1):
                v += scalar_bit(scalar, i - (w - 1) + j) << j
            v += scalar_bit(scalar, i - w)
            lsb = v & (~v + 1)
            s = (((1 if (lsb & 0xAA) != 0 else 0) << 0) |
                 ((1 if (lsb & 0xCC) != 0 else 0) << 1) |
                 ((1 if (lsb & 0xF0) != 0 else 0) << 2))
            ctx.next_index = i - (w - 1) + s
            ctx.next_digit = v >> s
            ctx.next_check -= w
    return ctx.next_digit if i == ctx.next_index else 0

def crypto_eddsa_check_equation(signature, public_key, h):
    minus_A, err1 = ge_frombytes_neg_vartime(public_key)
    minus_R, err2 = ge_frombytes_neg_vartime(signature)
    s = signature[32:64]

    s_int = sum(load32_le(s, i * 4) << (32 * i) for i in range(8))
    if err1 != 0 or err2 != 0 or s_int >= L_INT:
        return -1

    lutA = [GeCached() for _ in range(2)]
    minus_A2 = ge_double(minus_A)
    lutA[0] = ge_cache(minus_A)
    tmp = ge_add(minus_A2, lutA[0])
    lutA[1] = ge_cache(tmp)

    h_slide = SlideCtx(); slide_init(h_slide, h)
    s_slide = SlideCtx(); slide_init(s_slide, s)
    i = max(h_slide.next_check, s_slide.next_check)

    sum_p = Ge()
    sum_p.X = fe_0(); sum_p.Y = fe_1(); sum_p.Z = fe_1(); sum_p.T = fe_0()

    while i >= 0:
        sum_p = ge_double(sum_p)
        h_digit = slide_step(h_slide, 3, i, h)
        s_digit = slide_step(s_slide, 5, i, s)

        if h_digit > 0:
            sum_p = ge_add(sum_p, lutA[h_digit // 2])
        elif h_digit < 0:
            sum_p = ge_sub(sum_p, lutA[-h_digit // 2])

        if s_digit > 0:
            sum_p = ge_madd(sum_p, B_WINDOW[s_digit // 2])
        elif s_digit < 0:
            sum_p = ge_msub(sum_p, B_WINDOW[-s_digit // 2])

        i -= 1

    cached = ge_cache(minus_R)
    sum_p = ge_add(sum_p, cached)
    sum_p = ge_double(sum_p)
    sum_p = ge_double(sum_p)
    sum_p = ge_double(sum_p)
    check = ge_tobytes(sum_p)
    zero_point = b"\x01" + b"\x00" * 31
    return crypto_verify32(check, zero_point)

HALF_MOD_L = bytes([
    247,233,122,46,141,49,9,44,107,206,123,81,239,124,111,10,
    0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,8,
])
HALF_ONES = bytes([
    142,74,204,70,186,24,118,107,184,231,190,57,250,173,119,99,
    255,255,255,255,255,255,255,255,255,255,255,255,255,255,255,7,
])

def lookup_add(p, comb, scalar, i):
    teeth = ((scalar_bit(scalar, i)) |
             (scalar_bit(scalar, i + 32) << 1) |
             (scalar_bit(scalar, i + 64) << 2) |
             (scalar_bit(scalar, i + 96) << 3))
    high = teeth >> 3
    index = (teeth ^ (high - 1)) & 7
    elem = comb[index]
    tmp_c = GePrecomp(fe_copy(elem.Yp), fe_copy(elem.Ym), fe_copy(elem.T2))
    tmp_a = fe_neg(tmp_c.T2)
    if (high ^ 1) != 0:
        tmp_c.T2, tmp_a = tmp_a, tmp_c.T2
        tmp_c.Yp, tmp_c.Ym = tmp_c.Ym, tmp_c.Yp
    return ge_madd(p, tmp_c)

def ge_scalarmult_base(scalar):
    s_scalar = bytearray(32)
    crypto_eddsa_mul_add(s_scalar, scalar, HALF_MOD_L, HALF_ONES)
    p = Ge()
    p.X = fe_0(); p.Y = fe_1(); p.Z = fe_1(); p.T = fe_0()
    p = lookup_add(p, B_COMB_LOW, s_scalar, 31)
    p = lookup_add(p, B_COMB_HIGH, s_scalar, 31 + 128)
    for i in range(30, -1, -1):
        p = ge_double(p)
        p = lookup_add(p, B_COMB_LOW, s_scalar, i)
        p = lookup_add(p, B_COMB_HIGH, s_scalar, i + 128)
    return p

def crypto_eddsa_scalarbase(point, scalar):
    P = ge_scalarmult_base(scalar)
    point[:32] = ge_tobytes(P)

def crypto_eddsa_key_pair(secret_key, public_key, seed):
    a = bytearray(64)
    a[:32] = seed[:32]
    secret_key[:32] = a[:32]
    crypto_blake2b(a, 64, a[:32], 32)
    a_trimmed = bytearray(32)
    crypto_eddsa_trim_scalar(a_trimmed, a[:32])
    pk_tmp = bytearray(32)
    crypto_eddsa_scalarbase(pk_tmp, a_trimmed)
    secret_key[32:64] = pk_tmp
    public_key[:32] = pk_tmp

def hash_reduce_blake(h, *buffers):
    ctx = Blake2bCtx()
    crypto_blake2b_init(ctx, 64)
    for buf in buffers:
        if buf:
            crypto_blake2b_update(ctx, buf, len(buf))
    h_64 = bytearray(64)
    crypto_blake2b_final(ctx, h_64)
    crypto_eddsa_reduce(h, h_64)

def crypto_eddsa_sign(signature, secret_key, message, message_size):
    a = bytearray(64)
    r = bytearray(32)
    h = bytearray(32)
    R = bytearray(32)

    crypto_blake2b(a, 64, secret_key[:32], 32)
    crypto_eddsa_trim_scalar(a, a[:32])
    hash_reduce_blake(r, a[32:64], message[:message_size])
    crypto_eddsa_scalarbase(R, r)
    hash_reduce_blake(h, R, secret_key[32:64], message[:message_size])
    signature[:32] = R
    res_mul = bytearray(32)
    crypto_eddsa_mul_add(res_mul, h, a[:32], r)
    signature[32:64] = res_mul

def crypto_eddsa_check(signature, public_key, message, message_size):
    h = bytearray(32)
    hash_reduce_blake(h, signature[:32], public_key[:32], message[:message_size])
    return crypto_eddsa_check_equation(signature, public_key, h)

# --- Ed25519 (SHA-512 based) ---
def crypto_ed25519_key_pair(secret_key, public_key, seed):
    a = bytearray(64)
    a[:32] = seed[:32]
    secret_key[:32] = a[:32]
    crypto_sha512(a, a[:32], 32)
    a_trimmed = bytearray(32)
    crypto_eddsa_trim_scalar(a_trimmed, a[:32])
    pk_tmp = bytearray(32)
    crypto_eddsa_scalarbase(pk_tmp, a_trimmed)
    public_key[:32] = pk_tmp
    secret_key[32:64] = pk_tmp

def hash_reduce_sha512(h, *buffers):
    ctx = Sha512Ctx()
    crypto_sha512_init(ctx)
    for buf in buffers:
        if buf:
            crypto_sha512_update(ctx, buf, len(buf))
    h_64 = bytearray(64)
    crypto_sha512_final(ctx, h_64)
    crypto_eddsa_reduce(h, h_64)

def ed25519_dom_sign(signature, secret_key, dom, dom_size, message, message_size):
    a = bytearray(64)
    r = bytearray(32)
    h = bytearray(32)
    R = bytearray(32)
    pk = secret_key[32:64]

    crypto_sha512(a, secret_key[:32], 32)
    crypto_eddsa_trim_scalar(a, a[:32])
    dom_bytes = dom[:dom_size] if dom else None
    hash_reduce_sha512(r, dom_bytes, a[32:64], message[:message_size])
    crypto_eddsa_scalarbase(R, r)
    hash_reduce_sha512(h, dom_bytes, R, pk, message[:message_size])
    signature[:32] = R
    res_mul = bytearray(32)
    crypto_eddsa_mul_add(res_mul, h, a[:32], r)
    signature[32:64] = res_mul

def crypto_ed25519_sign(signature, secret_key, message, message_size):
    ed25519_dom_sign(signature, secret_key, None, 0, message, message_size)

def crypto_ed25519_check(signature, public_key, message, message_size):
    h_ram = bytearray(32)
    hash_reduce_sha512(h_ram, None, signature[:32], public_key[:32], message[:message_size])
    return crypto_eddsa_check_equation(signature, public_key, h_ram)

ED25519_DOMAIN = b"SigEd25519 no Ed25519 collisions\x01\x00"

def crypto_ed25519_ph_sign(signature, secret_key, message_hash):
    ed25519_dom_sign(signature, secret_key, ED25519_DOMAIN, len(ED25519_DOMAIN), message_hash, 64)

def crypto_ed25519_ph_check(signature, public_key, message_hash):
    h_ram = bytearray(32)
    hash_reduce_sha512(h_ram, ED25519_DOMAIN, signature[:32], public_key[:32], message_hash[:64])
    return crypto_eddsa_check_equation(signature, public_key, h_ram)


# --- Elligator 2 & Dirty Keys ---
def select_lop(x, k, cofactor):
    out = fe_0()
    fe_ccopy(out, k, (cofactor >> 1) & 1)
    fe_ccopy(out, x, cofactor & 1)
    tmp = fe_neg(out)
    fe_ccopy(out, tmp, (cofactor >> 2) & 1)
    return out

def crypto_x25519_dirty_fast(public_key, secret_key):
    scalar = bytearray(32)
    crypto_eddsa_trim_scalar(scalar, secret_key)
    pk = ge_scalarmult_base(scalar)

    t1 = select_lop(FE_LOP_X, FE_SQRT_MINUS_1, secret_key[0])
    t2 = select_lop(FE_LOP_Y, FE_ONE, secret_key[0] + 2)

    low_order_point = GePrecomp()
    low_order_point.Yp = fe_add(t2, t1)
    low_order_point.Ym = fe_sub(t2, t1)
    low_order_point.T2 = fe_mul(t2, t1)
    low_order_point.T2 = fe_mul(low_order_point.T2, FE_D2)

    pk = ge_madd(pk, low_order_point)

    t1 = fe_add(pk.Z, pk.Y)
    t2 = fe_sub(pk.Z, pk.Y)
    t2 = fe_invert(t2)
    t1 = fe_mul(t1, t2)
    public_key[:32] = fe_tobytes(t1)

def add_xl(s, x):
    mod8 = x & 7
    carry = 0
    for i in range(8):
        s_val = load32_le(s, i * 4)
        carry = carry + s_val + L_LIMBS[i] * mod8
        store32_le_into(s, i * 4, carry & 0xffffffff)
        carry >>= 32

DIRTY_BASE_POINT = bytes([
    0xd8, 0x86, 0x1a, 0xa2, 0x78, 0x7a, 0xd9, 0x26,
    0x8b, 0x74, 0x74, 0xb6, 0x82, 0xe3, 0xbe, 0xc3,
    0xce, 0x36, 0x9a, 0x1e, 0x5e, 0x31, 0x47, 0xa2,
    0x6d, 0x37, 0x7c, 0xfd, 0x20, 0xb5, 0xdf, 0x75,
])

def crypto_x25519_dirty_small(public_key, secret_key):
    scalar = bytearray(32)
    crypto_eddsa_trim_scalar(scalar, secret_key)
    add_xl(scalar, secret_key[0])
    scalarmult(public_key, scalar, DIRTY_BASE_POINT, 256)

def crypto_elligator_map(curve, hidden):
    r = fe_frombytes_mask(hidden, 2)
    r = fe_sq(r)
    t1 = fe_add(r, r)
    u = fe_add(t1, FE_ONE)
    t2 = fe_sq(u)
    t3 = fe_mul(FE_A2, t1)
    t3 = fe_sub(t3, t2)
    t3 = fe_mul(t3, FE_A)
    t1_mul = fe_mul(t2, u)
    t1_mul = fe_mul(t3, t1_mul)
    isr, is_square = invsqrt(t1_mul)

    u_res = fe_mul(r, FE_UFACTOR)
    if is_square:
        u_res = FE_ONE
    t1_sq = fe_sq(isr)
    u_res = fe_mul(u_res, FE_A)
    u_res = fe_mul(u_res, t3)
    u_res = fe_mul(u_res, t2)
    u_res = fe_mul(u_res, t1_sq)
    u_res = fe_neg(u_res)
    curve[:32] = fe_tobytes(u_res)

def crypto_elligator_rev(hidden, public_key, tweak):
    t1 = fe_frombytes(public_key)
    t2 = fe_add(t1, FE_A)
    t3 = fe_mul(t1, t2)
    t3 = fe_mul_small(t3, -2)
    isr, is_square = invsqrt(t3)
    if is_square:
        if (tweak & 1) != 0:
            t1 = t2
        t3 = fe_mul(t1, isr)
        t1_chk = fe_mul_small(t3, 2)
        t2_neg = fe_neg(t3)
        if fe_isodd(t1_chk):
            t3 = t2_neg
        h_bytes = bytearray(fe_tobytes(t3))
        h_bytes[31] |= (tweak & 0xc0)
        hidden[:32] = h_bytes
        return 0
    return -1

def crypto_elligator_key_pair(hidden, secret_key, seed):
    pk = bytearray(32)
    buf = bytearray(64)
    buf[32:64] = seed[:32]
    zero8 = b"\x00" * 8
    hidden_tmp = bytearray(32)
    while True:
        crypto_chacha20_djb(buf, None, 64, buf[32:64], zero8, 0)
        crypto_x25519_dirty_fast(pk, buf[:32])
        if crypto_elligator_rev(hidden_tmp, pk, buf[32]) == 0:
            buf[32:64] = hidden_tmp
            break
    hidden[:32] = buf[32:64]
    secret_key[:32] = buf[:32]

def redc(u, x_16):
    x_val = sum(x_16[i] << (32 * i) for i in range(16))
    r_val = (x_val * pow(2, -256, L_INT)) % L_INT
    for i in range(8):
        u[i] = (r_val >> (32 * i)) & 0xffffffff

def crypto_x25519_inverse(blind_salt, private_key, curve_point):
    scalar = bytearray(32)
    crypto_eddsa_trim_scalar(scalar, private_key)
    s_int = sum(load32_le(scalar, i * 4) << (32 * i) for i in range(8)) % L_INT

    inv_s = pow(s_int, L_INT - 2, L_INT)
    for i in range(8):
        store32_le_into(scalar, i * 4, (inv_s >> (32 * i)) & 0xffffffff)

    add_xl(scalar, scalar[0] * 3)
    scalarmult(blind_salt, scalar, curve_point, 256)


# --- AEAD Operations ---
def lock_auth(mac, auth_key, ad, ad_size, cipher_text, text_size):
    sizes = store64_le(ad_size) + store64_le(text_size)
    poly_ctx = Poly1305Ctx()
    crypto_poly1305_init(poly_ctx, auth_key)
    if ad_size > 0:
        crypto_poly1305_update(poly_ctx, ad, ad_size)
        gap_ad = (~ad_size + 1) & 15
        if gap_ad > 0:
            crypto_poly1305_update(poly_ctx, b"\x00" * gap_ad, gap_ad)
    if text_size > 0:
        crypto_poly1305_update(poly_ctx, cipher_text, text_size)
        gap_ct = (~text_size + 1) & 15
        if gap_ct > 0:
            crypto_poly1305_update(poly_ctx, b"\x00" * gap_ct, gap_ct)
    crypto_poly1305_update(poly_ctx, sizes, 16)
    crypto_poly1305_final(poly_ctx, mac)

class AeadCtx:
    def __init__(self):
        self.counter = 0
        self.key = bytearray(32)
        self.nonce = bytearray(8)

def crypto_aead_init_x(ctx, key, nonce):
    crypto_chacha20_h(ctx.key, key, nonce[:16])
    ctx.nonce[:8] = nonce[16:24]
    ctx.counter = 0

def crypto_aead_init_djb(ctx, key, nonce):
    ctx.key[:32] = key[:32]
    ctx.nonce[:8] = nonce[:8]
    ctx.counter = 0

def crypto_aead_init_ietf(ctx, key, nonce):
    ctx.key[:32] = key[:32]
    ctx.nonce[:8] = nonce[4:12]
    ctx.counter = load32_le(nonce, 0) << 32

def crypto_aead_write(ctx, cipher_text, mac, ad, ad_size, plain_text, text_size):
    auth_key = bytearray(64)
    crypto_chacha20_djb(auth_key, None, 64, ctx.key, ctx.nonce, ctx.counter)
    crypto_chacha20_djb(cipher_text, plain_text, text_size, ctx.key, ctx.nonce, ctx.counter + 1)
    lock_auth(mac, auth_key[:32], ad, ad_size, cipher_text, text_size)
    ctx.key[:32] = auth_key[32:64]

def crypto_aead_read(ctx, plain_text, mac, ad, ad_size, cipher_text, text_size):
    auth_key = bytearray(64)
    real_mac = bytearray(16)
    crypto_chacha20_djb(auth_key, None, 64, ctx.key, ctx.nonce, ctx.counter)
    lock_auth(real_mac, auth_key[:32], ad, ad_size, cipher_text, text_size)
    mismatch = crypto_verify16(mac, real_mac)
    if mismatch == 0:
        crypto_chacha20_djb(plain_text, cipher_text, text_size, ctx.key, ctx.nonce, ctx.counter + 1)
        ctx.key[:32] = auth_key[32:64]
    return mismatch

def crypto_aead_lock(cipher_text, mac, key, nonce, ad, ad_size, plain_text, text_size):
    ctx = AeadCtx()
    crypto_aead_init_x(ctx, key, nonce)
    crypto_aead_write(ctx, cipher_text, mac, ad, ad_size, plain_text, text_size)

def crypto_aead_unlock(plain_text, mac, key, nonce, ad, ad_size, cipher_text, text_size):
    ctx = AeadCtx()
    crypto_aead_init_x(ctx, key, nonce)
    return crypto_aead_read(ctx, plain_text, mac, ad, ad_size, cipher_text, text_size)
