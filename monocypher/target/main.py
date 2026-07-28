# Python runner for Monocypher test harness

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from target.monocypher import (
    crypto_verify16, crypto_verify32, crypto_verify64, crypto_wipe,
    crypto_chacha20_h, crypto_chacha20_djb, crypto_chacha20_ietf, crypto_chacha20_x,
    crypto_poly1305, crypto_blake2b, crypto_blake2b_keyed,
    crypto_sha512, crypto_sha512_hmac, crypto_sha512_hkdf,
    crypto_argon2, crypto_x25519, crypto_x25519_public_key,
    crypto_x25519_to_eddsa, crypto_eddsa_to_x25519,
    crypto_eddsa_key_pair, crypto_eddsa_sign, crypto_eddsa_check,
    crypto_eddsa_trim_scalar, crypto_eddsa_reduce, crypto_eddsa_mul_add,
    crypto_eddsa_scalarbase, crypto_eddsa_check_equation,
    crypto_ed25519_key_pair, crypto_ed25519_sign, crypto_ed25519_check,
    crypto_ed25519_ph_sign, crypto_ed25519_ph_check,
    crypto_x25519_dirty_fast, crypto_x25519_dirty_small,
    crypto_elligator_map, crypto_elligator_rev, crypto_elligator_key_pair,
    crypto_x25519_inverse,
    AeadCtx, crypto_aead_init_x, crypto_aead_init_djb, crypto_aead_init_ietf,
    crypto_aead_lock, crypto_aead_unlock, crypto_aead_write, crypto_aead_read,
    load32_le, load64_le, store64_le
)

def print_hex(data):
    if data is None:
        print(":")
    else:
        print(bytes(data).hex() + ":")

def read_line():
    line = sys.stdin.readline()
    if not line:
        return None
    line = line.strip()
    if line.endswith(':'):
        line = line[:-1]
    return line

def read_hex_param():
    line = read_line()
    if line is None:
        return b""
    if not line:
        return b""
    return bytes.fromhex(line)

def main():
    func_name = read_line()
    if not func_name:
        sys.stderr.write("empty input\n")
        sys.exit(1)

    if func_name == "crypto_verify16":
        a = read_hex_param()
        b = read_hex_param()
        res = crypto_verify16(a, b)
        print(f"{res & 0xffffffff:02x}:")

    elif func_name == "crypto_verify32":
        a = read_hex_param()
        b = read_hex_param()
        res = crypto_verify32(a, b)
        print(f"{res & 0xffffffff:02x}:")

    elif func_name == "crypto_verify64":
        a = read_hex_param()
        b = read_hex_param()
        res = crypto_verify64(a, b)
        print(f"{res & 0xffffffff:02x}:")

    elif func_name == "crypto_wipe":
        line = read_line()
        buf = bytearray.fromhex(line)
        for i in range(len(buf)):
            buf[i] = 0
        print_hex(buf)

    elif func_name == "crypto_chacha20_h":
        key = read_hex_param()
        in_buf = read_hex_param()
        out = bytearray(32)
        crypto_chacha20_h(out, key, in_buf)
        print_hex(out)

    elif func_name == "crypto_chacha20_djb":
        key = read_hex_param()
        nonce = read_hex_param()
        plain = read_hex_param()
        ctr_buf = read_hex_param()
        ctr = load64_le(ctr_buf)
        cipher = bytearray(len(plain))
        new_ctr = crypto_chacha20_djb(cipher, plain, len(plain), key, nonce, ctr)
        print_hex(cipher)
        print_hex(store64_le(new_ctr))

    elif func_name == "crypto_chacha20_ietf":
        key = read_hex_param()
        nonce = read_hex_param()
        plain = read_hex_param()
        ctr_buf = read_hex_param()
        ctr = load32_le(ctr_buf)
        cipher = bytearray(len(plain))
        new_ctr = crypto_chacha20_ietf(cipher, plain, len(plain), key, nonce, ctr)
        print_hex(cipher)
        ncb = bytearray(4)
        for i in range(4):
            ncb[i] = new_ctr & 0xff
            new_ctr >>= 8
        print_hex(ncb)

    elif func_name == "crypto_chacha20_x":
        key = read_hex_param()
        nonce = read_hex_param()
        plain = read_hex_param()
        ctr_buf = read_hex_param()
        ctr = load64_le(ctr_buf)
        cipher = bytearray(len(plain))
        new_ctr = crypto_chacha20_x(cipher, plain, len(plain), key, nonce, ctr)
        print_hex(cipher)
        print_hex(store64_le(new_ctr))

    elif func_name == "crypto_poly1305":
        key = read_hex_param()
        msg = read_hex_param()
        mac = bytearray(16)
        crypto_poly1305(mac, msg, len(msg), key)
        print_hex(mac)

    elif func_name == "crypto_blake2b":
        msg = read_hex_param()
        hash_out = bytearray(64)
        crypto_blake2b(hash_out, 64, msg, len(msg))
        print_hex(hash_out)

    elif func_name == "crypto_blake2b_keyed":
        msg = read_hex_param()
        key = read_hex_param()
        hash_out = bytearray(64)
        crypto_blake2b_keyed(hash_out, 64, key, min(len(key), 64), msg, len(msg))
        print_hex(hash_out)

    elif func_name == "crypto_sha512":
        msg = read_hex_param()
        hash_out = bytearray(64)
        crypto_sha512(hash_out, msg, len(msg))
        print_hex(hash_out)

    elif func_name == "crypto_sha512_hmac":
        key = read_hex_param()
        msg = read_hex_param()
        hmac = bytearray(64)
        crypto_sha512_hmac(hmac, key, len(key), msg, len(msg))
        print_hex(hmac)

    elif func_name == "crypto_sha512_hkdf":
        ikm = read_hex_param()
        salt = read_hex_param()
        info = read_hex_param()
        okm_line = read_hex_param()
        okm_len = len(okm_line)
        okm = bytearray(okm_len)
        crypto_sha512_hkdf(okm, okm_len, ikm, len(ikm), salt, len(salt), info, len(info))
        print_hex(okm)

    elif func_name == "crypto_argon2":
        algo_b = read_hex_param()
        blocks_b = read_hex_param()
        passes_b = read_hex_param()
        lanes_b = read_hex_param()
        pass_b = read_hex_param()
        salt_b = read_hex_param()
        key_b = read_hex_param()
        ad_b = read_hex_param()
        hash_line = read_hex_param()
        hash_size = len(hash_line)

        config = {
            'algorithm': load32_le(algo_b),
            'nb_blocks': load32_le(blocks_b),
            'nb_passes': load32_le(passes_b),
            'nb_lanes': load32_le(lanes_b),
        }
        inputs = {'pass': pass_b, 'pass_size': len(pass_b), 'salt': salt_b, 'salt_size': len(salt_b)}
        extras = {'key': key_b, 'key_size': len(key_b), 'ad': ad_b, 'ad_size': len(ad_b)}
        work_area = None
        hash_out = bytearray(hash_size)
        crypto_argon2(hash_out, hash_size, work_area, config, inputs, extras)
        print_hex(hash_out)

    elif func_name == "crypto_x25519":
        sk = read_hex_param()
        pk = read_hex_param()
        ss = bytearray(32)
        crypto_x25519(ss, sk, pk)
        print_hex(ss)

    elif func_name == "crypto_x25519_public_key":
        sk = read_hex_param()
        pk = bytearray(32)
        crypto_x25519_public_key(pk, sk)
        print_hex(pk)

    elif func_name == "crypto_x25519_to_eddsa":
        x2 = read_hex_param()
        ed = bytearray(32)
        crypto_x25519_to_eddsa(ed, x2)
        print_hex(ed)

    elif func_name == "crypto_eddsa_to_x25519":
        ed = read_hex_param()
        x2 = bytearray(32)
        crypto_eddsa_to_x25519(x2, ed)
        print_hex(x2)

    elif func_name == "crypto_eddsa_key_pair":
        seed = read_hex_param()
        sk = bytearray(64)
        pk = bytearray(32)
        crypto_eddsa_key_pair(sk, pk, seed)
        print_hex(sk)
        print_hex(pk)

    elif func_name == "crypto_eddsa_sign":
        sk = read_hex_param()
        pk = read_hex_param()
        msg = read_hex_param()
        fat_sk = bytearray(64)
        fat_sk[:32] = sk[:32]
        fat_sk[32:64] = pk[:32]
        sig = bytearray(64)
        crypto_eddsa_sign(sig, fat_sk, msg, len(msg))
        print_hex(sig)

    elif func_name == "crypto_eddsa_check":
        sig = read_hex_param()
        pk = read_hex_param()
        msg = read_hex_param()
        r = crypto_eddsa_check(sig, pk, msg, len(msg))
        print(f"{(r & 0xff):02x}:")

    elif func_name == "crypto_eddsa_trim_scalar":
        in_buf = read_hex_param()
        out = bytearray(32)
        crypto_eddsa_trim_scalar(out, in_buf)
        print_hex(out)

    elif func_name == "crypto_eddsa_reduce":
        expanded = read_hex_param()
        reduced = bytearray(32)
        crypto_eddsa_reduce(reduced, expanded)
        print_hex(reduced)

    elif func_name == "crypto_eddsa_mul_add":
        a = read_hex_param()
        b = read_hex_param()
        c = read_hex_param()
        r = bytearray(32)
        crypto_eddsa_mul_add(r, a, b, c)
        print_hex(r)

    elif func_name == "crypto_eddsa_scalarbase":
        scalar = read_hex_param()
        point = bytearray(32)
        crypto_eddsa_scalarbase(point, scalar)
        print_hex(point)

    elif func_name == "crypto_eddsa_check_equation":
        sig = read_hex_param()
        pk = read_hex_param()
        hram = read_hex_param()
        rv = crypto_eddsa_check_equation(sig, pk, hram)
        print(f"{(rv & 0xff):02x}:")

    elif func_name == "crypto_ed25519_key_pair":
        seed = read_hex_param()
        sk = bytearray(64)
        pk = bytearray(32)
        crypto_ed25519_key_pair(sk, pk, seed)
        print_hex(sk)
        print_hex(pk)

    elif func_name == "crypto_ed25519_sign":
        sk = read_hex_param()
        pk = read_hex_param()
        msg = read_hex_param()
        fat_sk = bytearray(64)
        fat_sk[:32] = sk[:32]
        fat_sk[32:64] = pk[:32]
        sig = bytearray(64)
        crypto_ed25519_sign(sig, fat_sk, msg, len(msg))
        print_hex(sig)

    elif func_name == "crypto_ed25519_check":
        sig = read_hex_param()
        pk = read_hex_param()
        msg = read_hex_param()
        r = crypto_ed25519_check(sig, pk, msg, len(msg))
        print(f"{(r & 0xff):02x}:")

    elif func_name == "crypto_ed25519_ph_sign":
        sk = read_hex_param()
        pk = read_hex_param()
        hash_msg = read_hex_param()
        fat_sk = bytearray(64)
        fat_sk[:32] = sk[:32]
        fat_sk[32:64] = pk[:32]
        sig = bytearray(64)
        crypto_ed25519_ph_sign(sig, fat_sk, hash_msg)
        print_hex(sig)

    elif func_name == "crypto_ed25519_ph_check":
        sig = read_hex_param()
        pk = read_hex_param()
        hash_msg = read_hex_param()
        r = crypto_ed25519_ph_check(sig, pk, hash_msg)
        print(f"{(r & 0xff):02x}:")

    elif func_name == "crypto_x25519_dirty_fast":
        sk = read_hex_param()
        pk = bytearray(32)
        crypto_x25519_dirty_fast(pk, sk)
        print_hex(pk)

    elif func_name == "crypto_x25519_dirty_small":
        sk = read_hex_param()
        pk = bytearray(32)
        crypto_x25519_dirty_small(pk, sk)
        print_hex(pk)

    elif func_name == "crypto_elligator_map":
        hidden = read_hex_param()
        curve = bytearray(32)
        crypto_elligator_map(curve, hidden)
        print_hex(curve)

    elif func_name == "crypto_elligator_rev":
        pk = read_hex_param()
        tweak = read_hex_param()[0]
        hidden = bytearray(32)
        r = crypto_elligator_rev(hidden, pk, tweak)
        if r == 0:
            print_hex(hidden)
        print(f"{(r & 0xff):02x}:")

    elif func_name == "crypto_elligator_key_pair":
        seed = read_hex_param()
        hidden = bytearray(32)
        sk = bytearray(32)
        crypto_elligator_key_pair(hidden, sk, seed)
        print_hex(hidden)
        print_hex(sk)

    elif func_name == "crypto_x25519_inverse":
        sk = read_hex_param()
        pk = read_hex_param()
        bs = bytearray(32)
        crypto_x25519_inverse(bs, sk, pk)
        print_hex(bs)

    elif func_name == "crypto_aead_lock":
        key = read_hex_param()
        nonce = read_hex_param()
        ad = read_hex_param()
        pt = read_hex_param()
        ct = bytearray(len(pt))
        mac = bytearray(16)
        crypto_aead_lock(ct, mac, key, nonce, ad, len(ad), pt, len(pt))
        print_hex(ct)
        print_hex(mac)

    elif func_name == "crypto_aead_unlock":
        key = read_hex_param()
        nonce = read_hex_param()
        ad = read_hex_param()
        ct = read_hex_param()
        mac = read_hex_param()
        pt = bytearray(len(ct))
        r = crypto_aead_unlock(pt, mac, key, nonce, ad, len(ad), ct, len(ct))
        if r == 0:
            print_hex(pt)
        print(f"{(r & 0xff):02x}:")

    elif func_name == "crypto_aead_write":
        key = read_hex_param()
        nonce = read_hex_param()
        ad = read_hex_param()
        pt = read_hex_param()
        ctx = AeadCtx()
        crypto_aead_init_ietf(ctx, key, nonce)
        ct = bytearray(len(pt))
        mac = bytearray(16)
        crypto_aead_write(ctx, ct, mac, ad, len(ad), pt, len(pt))
        print_hex(ct)
        print_hex(mac)

    elif func_name in ("crypto_aead_init_x", "do_crypto_aead_init_x"):
        key = read_hex_param()
        nonce = read_hex_param()
        ctx = AeadCtx()
        crypto_aead_init_x(ctx, key, nonce)
        print_hex(store64_le(ctx.counter) + ctx.key + ctx.nonce)

    elif func_name in ("crypto_aead_init_djb", "do_crypto_aead_init_djb"):
        key = read_hex_param()
        nonce = read_hex_param()
        ctx = AeadCtx()
        crypto_aead_init_djb(ctx, key, nonce)
        print_hex(store64_le(ctx.counter) + ctx.key + ctx.nonce)

    elif func_name in ("crypto_aead_init_ietf", "do_crypto_aead_init_ietf"):
        key = read_hex_param()
        nonce = read_hex_param()
        ctx = AeadCtx()
        crypto_aead_init_ietf(ctx, key, nonce)
        print_hex(store64_le(ctx.counter) + ctx.key + ctx.nonce)

    else:
        sys.stderr.write(f"Unknown function: {func_name}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
