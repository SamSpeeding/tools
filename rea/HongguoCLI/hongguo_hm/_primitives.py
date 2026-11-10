"""Arithmetic used only by Medusa v3 (not the video-decryption cipher).

Adapted and reduced from the locally audited reference algorithm. No network,
plugin import, device generation or reference-file dependency. See the signing
ADR for provenance and limitations. All three f13 branches and all four timestamp
selectors are required; the lookup table is protocol data, never executable code.
"""
from functools import lru_cache
import hashlib
from pathlib import Path

xtime = lambda a: (a << 1 ^ 27) & 255 if a & 128 else a << 1

s_box = bytes.fromhex(
    "fa7d086b9c59b34b045f39d0384a91990067a6209ff54d827326eedf18668333"
    "800319fbd9feaeaaa9b052c60bf379254e78b436ac5d1a279e88dbbd3c63ec49"
    "15c1301fdcb856d46ccdca0943c835a3ef1ef496d2fc0e727b9484d1ea455a62"
    "023fd31281342bdd7ee628f2a54613013b21f66137292a0ded8cafbf9d5cbb24"
    "760f75e45389e1988db19a65704f544c58ab6e6f8b23c407110cbacfa0a48ed8"
    "053d14b2da74c3d7e7bed67fde48163e8590a155b7774222c986502e17f96431"
    "2c9bf16d1c4468e3e9a89397cb3257ebe5716aadc0ccc7c5fd601da22d47a7e2"
    "51695e7ace0a41b6958ff7b987e03a06108ab5f85bd5f0bc92ff7c2fc2e81b40"
    "ec1bdabdba98910cb22b83413467fb0ad876b546055961237590872ae350154c"
    "acb179ebaee595470468f0863d518b0fca8ee4b94ef21282bc0ed5f7ef2825cf"
    "5b5de96a5502e133be93e7f5ad9d3e3924a8e2fa1757d07a0d0830d6b8a38dfd"
    "079ac41e6e226497d21db0bf45663f6cdddb2780a711dca6c552f8c0b6c85c00"
    "73607ba01913aac935484bd3a4cd9f99f3104440547e29f4061fa2aba12f3cf6"
    "af856236217f5edf201ab3b4e6ff72848f6526945a77ea4378c74acc2c146bc6"
    "e87453fcd41cce317003188c96383289f13a5fd7f9a969b7633758c23bc371cb"
    "9e92018a0b4d889bbb4f6d6fe0fea549de561609ed9cc12dee817dd97cd12e42"
    "5b4dc1a65dea44fd454e1ba13fd189e17d2faadbabad59cbb1ce9a28c9e0f670"
    "394ad7ff30f5ddbc573b118db2ee00b6e61a5a7cf9dec4cd2e80bbb94ca59f84"
    "08c66f426cf027e78b3a9c51fb6721754131a7ca20432ab7bfd97af2b5f88c2c"
    "23834f8f60a004133714e301c563665c7481df58bd68903dd2b334f419933229"
    "d649ae0d4bd8079eac1e2d0b40b872ba761071a8e4561d48fee5c24791da8726"
    "9d1f886bc098be25099733a385165e7fdc6e54e9f7a9c8e8c377d0822bec0262"
    "8a920e3eb00f05f3f19678388636183c24cf0ab453cc6165a4c794d5157e6def"
    "792235126a8e5206557b46645095e20cedd31703a29b99eb1cfcafd47369fa5f"
    "f72c1ebfc8e1f39f76807148aa94ad64fb89c660c332b34dd2e044dd5fa8b1c7"
    "682334c96d127fb7eb15bea9d17893a00c92a4d747e38ac270ab26419a79a7d8"
    "14858fc06f56d08c11b92e3ce29dcf0ede035d463ecd38430f335ad91a656c22"
    "3bfc30a688ea37a2b48d8e519cd640eef9f884f4ae97e9ca0a456757042f835c"
    "d5c5c482b6a391981f4aac96816ecb1b0908af1895497d54edfa16313adab866"
    "f5a5f1fe10010674cc63df7c2825f6ceb24f8be5bc8769bb8621070036e70b50"
    "599b1ce862581961f2bd275eba1de699423d0d2ab5dc5b29f02d4c537b6a734e"
    "3f75ff4ba1351755723920d3b0fdef02ec777ee42bdb90c1059e7ad4526b2413"
)

SV2 = (
    0xa7aefe20, 0x7149f1d6, 0x47e4ca07, 0xe9b58f67, 0x93b924de, 0xc614d0f5, 0x38afe0ef, 0xb2bbad73,
    0xe24444c3, 0x9d3aec9b, 0xdf7b37e4, 0xd8b16d40, 0xf8ac31b8, 0x76b9a90b, 0x31d833ee, 0x953fce64,
    0x353595a4, 0x4609c13b, 0x36925008, 0x8c6d0925, 0x5df5c177, 0x1cfbf52b, 0x8a4fa7f0, 0x114ca35e,
    0x8193f984, 0x7a7a8733, 0x316ab4d5, 0x3c20cfc9, 0xa6d84453, 0x3a18500c, 0x798ec47a, 0x97a76b28,
    0x66c4ff96, 0x51716443, 0x0dd2fc3b, 0xb5696da7, 0xbbeb3ac5, 0x5c53d204, 0xd32608ce, 0x7279b9ec,
    0xf4188ecf, 0xf7d793db, 0x332cc491, 0xab76ae15, 0x9bebe727, 0x18a01384, 0x5be9f8a7, 0x5f90a754,
    0x39b663c0, 0x36673c83, 0x7c92f514, 0x9d7d94d7, 0xe2e8d9aa, 0x5f7e9ea9, 0x7abd4551, 0x569e05da,
    0x40a25632, 0x3df5a9a5, 0xbab37d80, 0x454286dc, 0x3f5d4e78, 0x03d7b75d, 0xb1fe4af7, 0xa5ab26a3,
)

branch_2_orders = bytes.fromhex(
    "0f0704000908030a060b050d0e010c020f05080c0009020103070e060b0a0d04"
    "060500070c000a04080f010b0d09020e060b02050403080101070a000d0c090e"
    "0d070e0f0b0208030c0509010004060a0d0902060f0b0a040807000c0503010e"
    "0c090f07060f030e020d0405010b0a000c050a090e0802040407030f01060b00"
    "0b0f0408020a0700090d06010e03050c0b060a0508020c03070f0e090d000104"
    "0906080f050800040a0b030d01020c0e090d0c0604070a03030f00080105020e"
    "01000d0f090a0b0e0402080703060c0501080a0c0f0905060b000304020e070d"
    "04080f000c0f0e0d0a01060207090503040205080d0b0a0606000e0f070c0903"
    "0a08040f000b01060d0c0709030e05020a070b050f00020e0108030d0c060904"
    "0d070f08050f06040b0a0e0c090002030d0c020704010b0e0e08060f09050003"
)

class SM3:

    def __init__(self, data=b''):
        if isinstance(data, str):
            data = data.encode('utf-8')
        self._data = bytearray(data)

    def update(self, data):
        self._data.extend(data)

    def digest(self):
        data = bytes(self._data)
        bit_len = len(data) * 8
        data += b'\x80'
        data += b'\x00' * ((56 - len(data) % 64) % 64)
        data += bit_len.to_bytes(8, 'big')
        iv = [1937774191, 1226093241, 388252375, 3666478592, 2842636476, 372324522, 3817729613, 2969243214]

        def rol32(v, n):
            return (v << n | v >> 32 - n) & 4294967295
        for off in range(0, len(data), 64):
            block = data[off:off + 64]
            w = [int.from_bytes(block[i:i + 4], 'big') for i in range(0, 64, 4)]
            for j in range(16, 68):
                x = w[j - 16] ^ w[j - 9] ^ rol32(w[j - 3], 15)
                w.append((x ^ rol32(x, 15) ^ rol32(x, 23) ^ rol32(w[j - 13], 7) ^ w[j - 6]) & 4294967295)
            w1 = [w[j] ^ w[j + 4] for j in range(64)]
            a, b, c, d, e, f, g, h = iv
            for j in range(64):
                tj = 2043430169 if j < 16 else 2055708042
                ss1 = rol32(rol32(a, 12) + e + rol32(tj, j % 32) & 4294967295, 7)
                ss2 = ss1 ^ rol32(a, 12)
                ff = a ^ b ^ c if j < 16 else a & b | a & c | b & c
                gg = e ^ f ^ g if j < 16 else e & f | ~e & g
                tt1 = ff + d + ss2 + w1[j] & 4294967295
                tt2 = gg + h + ss1 + w[j] & 4294967295
                d, c, b, a = (c, rol32(b, 9), a, tt1)
                h, g, f, e = (g, rol32(f, 19), e, (tt2 ^ rol32(tt2, 9) ^ rol32(tt2, 17)) & 4294967295)
            iv = [(x ^ y) & 4294967295 for x, y in zip(iv, (a, b, c, d, e, f, g, h))]
        return b''.join((x.to_bytes(4, 'big') for x in iv))

def rol(num, shift):
    shift %= 32
    return (num << shift | num >> 32 - shift) & 4294967295

def rl8(x: int, k: int) -> int:
    n = 8
    s = k & n - 1
    return (x << s | x >> n - s) & 255

def ror32(value, count):
    count %= 32
    low = value << 32 - count
    value >>= count
    value |= low
    value &= 4294967295
    return value

def ror(value, count):
    count %= 64
    low = value << 64 - count
    value >>= count
    value |= low
    value &= 18446744073709551615
    return value

def get_key_hash(key, rand):
    to_hash = bytearray(68)
    to_hash[:32] = key
    to_hash[32:36] = rand.to_bytes(4, byteorder='little')
    to_hash[36:] = key
    d1 = rand >> 16 & 255
    d2 = d1 << 11 | rand >> 24
    d2 ^= d1 >> 5 ^ d1
    d2 = ~d2 & 4294967295
    return (SM3(to_hash).digest(), d2.to_bytes(4, 'little'))

def split_blocks(message, block_size=16, require_padding=True):
    assert len(message) % block_size == 0 or not require_padding
    return [message[i:i + 16] for i in range(0, len(message), block_size)]

def add_round_key(s, k):
    for i in range(4):
        for j in range(4):
            s[i][j] ^= k[i][j]

def add_round_key_con(s, k, con):
    for i in range(4):
        for j in range(4):
            s[i][j] ^= k[i][con[j]]

def bytes2matrix(text):
    """ Converts a 16-byte array into a 4x4 matrix.  """
    return [list(text[i:i + 4]) for i in range(0, len(text), 4)]

def xor_bytes(a, b):
    """ Returns a new byte array with the elements xor'ed. """
    return bytearray((i ^ j for i, j in zip(a, b)))

def matrix2bytes(matrix):
    """ Converts a 4x4 matrix into a 16-byte array.  """
    return bytearray(sum(matrix, []))

def mix_single_column(a, i):
    t = a[0][i] ^ a[1][i] ^ a[2][i] ^ a[3][i]
    u = a[0][i]
    a[0][i] ^= t ^ xtime(a[0][i] ^ a[1][i])
    a[1][i] ^= t ^ xtime(a[1][i] ^ a[2][i])
    a[2][i] ^= t ^ xtime(a[2][i] ^ a[3][i])
    a[3][i] ^= t ^ xtime(a[3][i] ^ u)

def mix_columns(s):
    for i in range(4):
        mix_single_column(s, i)

class AES_V3:
    r_con2 = [[1, 0, 2, 3], [2, 0, 3, 1], [0, 1, 3, 2], [1, 0, 2, 3]]
    r_orders = [[0, 9, 14, 11, 4, 13, 2, 7, 8, 1, 6, 15, 12, 5, 10, 3], [0, 9, 14, 15, 4, 13, 2, 7, 8, 1, 6, 3, 12, 5, 10, 11], [0, 9, 14, 7, 4, 13, 2, 11, 8, 1, 6, 3, 12, 5, 10, 15], [0, 9, 14, 11, 4, 13, 2, 7, 8, 1, 6, 15, 12, 5, 10, 3]]

    def __init__(self, aes_key, khronos):
        self.word_size = khronos & 3
        self.aes_key = aes_key
        self.s_box = s_box[self.word_size << 8:]
        self.master_key = self._expand_key()
        self._key_matrices = bytes2matrix(self.master_key)
        self.con2 = self.r_con2[self.word_size]
        self.order = self.r_orders[self.word_size]

    def _expand_key(self):
        init_values = [3389152732, 2185086278, 3376547203, 3264750175]
        init_value = init_values[self.word_size]
        mk = bytearray(init_value.to_bytes(4, 'little'))
        mk = mk * 4
        mk = xor_bytes(mk, self.aes_key)
        mk += bytearray(32)
        rounds = 8
        for i in range(4, 12):
            idx = 4 * (i - 1)
            k0, k1, k2, k3 = (mk[idx], mk[idx + 1], mk[idx + 2], mk[idx + 3])
            if i & 3 == 0:
                k00 = init_value >> (rounds & 24) ^ self.s_box[k1]
                k1 = self.s_box[k2]
                k2 = self.s_box[k3]
                k3 = self.s_box[k0]
                k0 = k00 & 255
            rounds += 2
            mk[idx + 4] = k0 ^ mk[idx - 12]
            mk[idx + 5] = k1 ^ mk[idx - 11]
            mk[idx + 6] = k2 ^ mk[idx - 10]
            mk[idx + 7] = k3 ^ mk[idx - 9]
        return mk

    @staticmethod
    def sum_data(data):
        key = bytearray(32)
        for i in range(31):
            idx = i * 8
            n0 = data[idx] >> 4 & 2
            n1 = n0 | data[idx + 1] & 64
            n2 = n1 | data[idx + 2] >> 2 & 1
            n3 = n2 | data[idx + 3] << 3 & -128
            n4 = n3 | data[idx + 4] >> 1 & 4
            n5 = n4 | data[idx + 5] << 3 & 16
            n6 = n5 | data[idx + 6] << 5 & 32
            n7 = n6 | data[idx + 7] >> 4 & 8
            key[i] = n7 & 255
        key[31] = 1
        return key

    @staticmethod
    def mix_columns(data, key):
        data = bytearray(data)
        for i in range(31):
            kk = key[i]
            idx = i * 8
            data[idx + 0] = data[idx + 0] & -33 | kk << 4 & 255 & 32
            data[idx + 1] = data[idx + 1] & -65 | kk & 64
            data[idx + 2] = data[idx + 2] & -5 | kk * 4 & 4
            data[idx + 3] = data[idx + 3] & -17 | kk >> 3 & 16
            data[idx + 4] = data[idx + 4] & -9 | kk + kk & 8
            data[idx + 5] = data[idx + 5] & -3 | kk >> 3 & 2
            data[idx + 6] = data[idx + 6] & -2 | kk >> 5 & 1
            data[idx + 7] = data[idx + 7] & 127 | kk << 4 & 255 & -128
        return data

    def encrypt(self, data, iv):
        plaintext = self.sum_data(data)
        blocks = []
        previous = iv
        for plaintext_block in split_blocks(plaintext):
            x = xor_bytes(plaintext_block, previous)
            block = self.encrypt_block(x)
            blocks.append(block)
            previous = block
        key = b''.join(blocks)
        data = self.mix_columns(data, key)
        return key[-1:] + data

    def encrypt_block(self, plaintext):
        plain_state = bytes2matrix(plaintext)
        add_round_key_con(plain_state, self._key_matrices[0:4], self.con2)
        for i in range(1, 3):
            self.sub_bytes(plain_state)
            self.shift_rows(plain_state)
            if i == 1:
                self.shift_rows_con(plain_state, self.con2)
                mix_columns(plain_state)
            add_round_key_con(plain_state, self._key_matrices[i * 4:], self.con2)
        add_round_key(plain_state, self._key_matrices[4:])
        return matrix2bytes(plain_state)

    def shift_rows_con(self, s, c):
        for i in range(4):
            s[i][0], s[i][1], s[i][2], s[i][3] = (s[i][c[0]], s[i][c[1]], s[i][c[2]], s[i][c[3]])

    def shift_rows(self, s):
        bs = matrix2bytes(s)
        for i in range(4):
            for j in range(4):
                s[i][j] = bs[self.order[i * 4 + j]]

    def sub_bytes(self, s):
        for i in range(4):
            for j in range(4):
                s[i][j] = self.s_box[s[i][j]]
        s[0], s[1], s[2], s[3] = (s[self.con2[0]], s[self.con2[1]], s[self.con2[2]], s[self.con2[3]])


def sum_md5(data):
    check_sum = 539100192
    for i in range(12):
        if i % 2 == 0:
            temp = check_sum >> 3 ^ check_sum
            check_sum = data[i] ^ check_sum << 7
        else:
            temp = check_sum >> 5 ^ check_sum
            check_sum = data[i] | check_sum << 11
            check_sum ^= 4294967295
        check_sum ^= temp
        check_sum &= 4294967295
    check_sum |= 4
    check_sum ^= 16777216
    return check_sum

def md5sum_v3(message, rotation, orders, table_rotation):
    """The 64-step v3 MD5-like branch, with protocol-specific constants/orders."""
    constants = [ror32(value, table_rotation) for value in SV2]
    start = [ror32(value, rotation & 255) for value in
             (0x79e0f2fb, 0xc8b52570, 0xebc2f8cd, 0x7c104d93)]
    end = [ror32(value, (rotation + 6) & 255) for value in
           (0x19be4866, 0xe85986b4, 0xe19b326e, 0x71d1d7d4)]
    words = [int.from_bytes(message[i:i + 4], "little") for i in range(0, 64, 4)]
    shifts = ((7, 12, 17, 22), (5, 9, 14, 20), (4, 11, 16, 23), (6, 10, 15, 21))
    a, b, c, d = start
    for index in range(64):
        round_index = index // 16
        if round_index == 0:
            mixed = (b & c) | (~b & d)
        elif round_index == 1:
            mixed = (b & d) | (c & ~d)
        elif round_index == 2:
            mixed = b ^ c ^ d
        else:
            mixed = (c ^ (b | ~d)) & 0xffffffff
        value = (a + mixed + words[orders[index]] + constants[index]) & 0xffffffff
        a, b, c, d = d, b + rol(value, shifts[round_index][index % 4]), b, c
    digest = bytearray().join((((x + y) & 0xffffffff) ^ z).to_bytes(4, "little")
                              for x, y, z in zip(start, (a, b, c, d), end))
    return digest + sum_md5(digest).to_bytes(4, "little")

def bxor(b1, b2):
    b3 = bytearray(len(b1))
    for i in range(len(b1)):
        b3[i] = b1[i] ^ b2[i]
    return b3

def get_iv(iv, data):
    for i in range(len(data)):
        if i & 1 == 0:
            iv = iv >> 4 ^ iv ^ iv << 6 ^ data[i]
        else:
            iv = ~(iv >> 7 ^ iv ^ (data[i] | iv << 12))
        iv = iv & 4294967295
    return iv

def hash_f13(query_sm3, body_md5_bytes, ts_bytes, khronos):
    """Select one of three request-dependent bindings; all branches are needed."""
    iv = get_iv(539167016, query_sm3)
    iv = get_iv(iv, body_md5_bytes)
    iv = get_iv(iv, ts_bytes)
    iv_v0 = (iv & 15) * 171 >> 9
    branch = (iv & 15) - (iv_v0 * 3 & 255)
    if branch == 0:
        return branch_0(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes)
    elif branch == 1:
        return branch_1(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes)
    elif branch == 2:
        return branch_2(iv, khronos, query_sm3, body_md5_bytes, ts_bytes)
    else:
        raise Exception('no branch: ' + str(branch))

def branch_0(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes):
    tt01 = [3299313024, 3015769401, 3314308742, 3383376807, 4121406962, 2520526545]
    iv_v1 = tt01[iv_v0]
    count_v1 = iv_v1 + khronos + 1 & 255
    count_v2 = iv_v1 + khronos & 4294967295
    tt02 = [3954593711, 128638146, 3476129727, 3759225087, 1829502207, 1513137086, 3021657656, 873991864, 4063488879, 2980414668, 3435335111, 1204935505, 3579204574, 1890078625, 1464286226, 4151247496, 738688778, 3658336976, 4223168364, 4257533696, 1753874957, 3866543782, 2362848139, 440175886, 3437801579, 1792077067, 2689738519, 3698437251, 579197809, 3585400230, 1936688720, 1700802668, 1635574438, 3827515774, 172024131, 1414414386, 2296380202, 1902910176, 1279687304, 95566771, 3788552294, 3131301048, 2922607827, 3275233872, 386070363, 4268598120, 4038381384, 1309670328, 1923797261, 650459709, 4072464630, 3025499521, 1243971549, 2352054946, 2869640070, 1029569300, 1326462516, 3548074711, 1146027798, 3943314385, 1822977902, 2640807, 137919738, 1605596550]
    tt03 = [0] * 64
    for i in range(0, 64):
        tt03[i] = ror32(tt02[i], count_v1) & 4294967295
    n0 = count_v2 + 2 & 7
    pad = bytearray(4)
    seed = bytes([250, 69, 97, 215])
    for i in range(4):
        v = int.from_bytes(bytes([seed[i], seed[i]]), 'little')
        v = v >> n0
        pad[i] = v & 255
    count_v2 = count_v2 & 255
    init_value = [ror32(2059030472, count_v2), ror32(1729520903, count_v2), ror32(1677982208, count_v2), ror32(873419055, count_v2), ror32(984304912, count_v2), ror32(3005047866, count_v2), ror32(2874125293, count_v2), ror32(2152413264, count_v2)]
    data = query_sm3 + body_md5_bytes + ts_bytes + pad + bytes.fromhex(' 00 00 00 00 00 00 01 a0')
    di = [0] * (len(data) // 4)
    for i in range(len(data) // 4):
        di[i] = int.from_bytes(data[i * 4:i * 4 + 4], 'big')
    di0 = di[0]
    for i in range(112):
        di1, di14 = (di[i + 1], di[i + 14])
        r_di1 = rol(di1, 14) ^ rol(di1, 25) ^ di1 >> 3
        r_di2 = rol(di14, 13) ^ rol(di14, 15) ^ di14 >> 10
        di0 = di0 + di[i + 9] + r_di1 + r_di2
        di.append(di0 & 4294967295)
        di0 = di1
    if iv_v0 == 5:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 100, 2, 0, 3, 5, 4, 6, 7, 2, 1, 5)
    elif iv_v0 == 4:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 96, 0, 5, 6, 7, 3, 1, 2, 5, 4, 4)
    elif iv_v0 == 3:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 99, 3, 6, 2, 4, 5, 1, 0, 0, 7, 6)
    elif iv_v0 == 2:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 96, 7, 6, 2, 1, 4, 0, 5, 4, 3, 5)
    elif iv_v0 == 1:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 96, 0, 6, 7, 5, 3, 2, 1, 5, 4, 4)
    elif iv_v0 == 0:
        v_j = branch0_xor(init_value, iv_v1, di, tt03, 101, 5, 7, 6, 3, 2, 1, 0, 5, 4, 3)
    ret = bytearray(32)
    for i in range(8):
        ret[i * 4:i * 4 + 4] = (v_j[i] + init_value[i] & 4294967295).to_bytes(4, 'big')
    ret = bxor(ret[:16], ret[16:])
    sum = sum_md5(ret)
    ret += sum.to_bytes(4, 'little')
    return ret

def swap_v0(src, src_xor, constants, table, order, typ=None):
    """Two 8-word states, rotated through the branch-one lookup rounds."""
    state = [src[order[i]] ^ src_xor[i] for i in range(8)]
    key = src_xor[:]
    for round_index in range(10):
        key = [r00(*(key[i:] + key[:i]), 0, table) for i in range(8)]
        key[-1] ^= constants[round_index + 1]
        state = [r00(*(state[i:] + state[:i]), key[i], table) for i in range(8)]
    if typ is None:
        return [state[-i % 8] ^ src_xor[i] ^ src[i] for i in range(8)]
    result = [state[7-i] ^ typ[(i+1) % 8] for i in range(8)]
    result[6] ^= src[7]
    return result

def branch_1(iv_v0, khronos, query_sm3, body_md5_bytes, ts_bytes):
    tt1 = [2156567673, 4034494590, 3135207877, 2810565631, 2195211148]
    iv_v1 = tt1[iv_v0]
    c_v1 = iv_v1 + khronos & 255
    c_v1 = ror(khronos, c_v1)
    orders = bytes.fromhex('05 07 01 02 04 00 06 03 00 05 02 04 01 03 07 06\n    05 07 02 04 01 06 03 00 03 00 02 04 06 07 01 05\n    04 05 00 03 06 02 01 07 00 00 00 00 00 00 00 00')
    order1 = orders[iv_v0 * 8:iv_v0 * 8 + 8]
    iv_v1 = iv_v1 + khronos + 1 & 63
    tt1 = [9777009529093344619, 9220148185898762375, 12714308288559955293, 2298489136484332173, 1883403838777782770, 14627534573129331130, 3690803318557581848, 18375228976263348731, 782252806811451624, 7081731275062538215, 53211017926475378]
    tt2 = [0] * 11
    for i in range(0, 11):
        tt2[i] = ror(tt1[i], iv_v1)
    to_sign = bytearray(query_sm3 + body_md5_bytes + ts_bytes + bytes([128, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]))
    src = [0] * (len(to_sign) // 8)
    for i in range(len(to_sign) // 8):
        src[i] = int.from_bytes(to_sign[i * 8:i * 8 + 8], 'big')
    src_xor = [c_v1, c_v1, c_v1, c_v1, c_v1, c_v1, c_v1, c_v1]
    table_f = get_branch_1_table_f(iv_v0)
    swap = swap_v0(src, src_xor, tt2, table_f, order1)
    data = [0] * 8
    data[7] = 416
    src_xor = [swap[4], swap[3], swap[2], swap[1], swap[0], swap[7], swap[6], swap[5]]
    swap = swap_v0(data, src_xor, tt2, table_f, order1, swap)
    ret = bytearray(32)
    n = 0
    for i in range(7, -1, -1):
        pp = swap[i].to_bytes(8, 'little')
        ret[n + 0], ret[n + 1], ret[n + 2], ret[n + 3] = (pp[1], pp[3], pp[5], pp[6])
        n += 4
    for i in range(16):
        ret[i] ^= ret[i + 16]
    ret = ret[:16]
    sum = sum_md5(ret)
    ret += sum.to_bytes(4, 'little')
    return ret

def r00(r0, r1, r2, r3, r4, r5, r6, r7, tt, table_f, v=0):
    x = table_f(8 * (r0 >> 56))
    r1 = r1 >> 45 & 2040
    if tt > 0:
        x = x ^ tt
    x = x ^ table_f(r1 + 2048)
    r2 = r2 >> 37 & 2040
    x = x ^ table_f(r2 + 4096)
    r3 = r3 >> 29 & 2040
    x = x ^ table_f(r3 + 6144)
    r4 = r4 >> 21 & 2040
    x = x ^ table_f(r4 + 8192)
    r5 = r5 >> 13 & 2040
    x = x ^ table_f(r5 + 10240)
    r6 = r6 >> 8 & 255
    x = x ^ table_f(8 * r6 + 12288)
    r7 = r7 & 255
    x = x ^ table_f(8 * r7 + 14336)
    return x

def branch_2(iv, khronos, query_sm3, body_md5_bytes, ts_bytes):
    # Preserve the audited precedence: iv & (15 - 2), not (iv & 15) - 2.
    n0 = (iv & (15 - 2)) * 86
    iv_v0 = (n0 >> 15 & 255) + (n0 >> 8 & 255)
    t001 = [2306929307, 3948190847, 2961647323, 3557602790, 3908393444]
    n1 = t001[iv_v0]
    count_v1 = n1 + khronos + 1 & 255
    count_v2 = n1 + khronos & 4294967295
    n0 = count_v2 + 5 & 7
    pad = bytearray(8)
    seed = bytes([132, 150, 119, 157, 212, 21, 11, 248])
    for i in range(8):
        v = int.from_bytes(bytes([seed[i], seed[i]]), 'little')
        v = v >> n0
        pad[i] = v & 255
    data = query_sm3 + body_md5_bytes + ts_bytes + pad + bytes.fromhex('a0 01 00 00')
    idx = iv_v0 << 6
    ret = md5sum_v3(data, count_v2, branch_2_orders[idx:idx + 64], count_v1)
    return ret

def branch0_xor(data, base, di, tt03, round, x1, x2, x3, x4, x5, x6, x7, x8, x9, x10):
    d = data[:]
    for i in range(round):
        offset = base + i
        n0 = di[offset & 127]
        n1 = (d[x3] ^ d[x4]) & d[x1] ^ d[x3]
        n2 = rol(d[x1], 26) ^ rol(d[x1], 21) ^ rol(d[x1], 7)
        offset = offset & 63
        n3 = tt03[offset]
        n4 = n0 + n1 + n2 + n3 + d[x5] & 4294967295
        n5 = rol(d[x2], 30) ^ rol(d[x2], 19) ^ rol(d[x2], 10)
        n6 = d[x2] & d[x6] | (d[x2] | d[x6]) & d[x7]
        n7 = n5 + n6
        o = d[x9]
        d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7] = (d[7], d[0], d[1], d[2], d[3], d[4], d[5], d[6])
        d[x10] = n7 + n4 & 4294967295
        d[x8] = o + n4 & 4294967295
    return d

@lru_cache(maxsize=1)
def _branch_one_bytes():
    table = Path(__file__).with_name("medusa-v3-table.bin").read_bytes()
    if len(table) != 81936 or hashlib.sha256(table).hexdigest() != "239ddf955d14a008311b8c3adcf05713b858954068fff02ab19c2ba81e31d1d3":
        raise ValueError("Medusa v3 lookup table is missing or corrupted")
    return table


def get_branch_1_table_f(index):
    table = _branch_one_bytes()
    offset = index << 14
    return lambda position: int.from_bytes(table[offset + position:offset + position + 8], "little")
