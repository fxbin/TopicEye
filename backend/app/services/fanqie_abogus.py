"""
番茄小说 a_bogus 反爬签名生成器。

来源: https://github.com/wengchengjian/fanqie-rank-mcp (MIT)
移植自参考项目 tomato-rank-download 的 Rust 实现。

模拟客户端 JavaScript 的签名逻辑：
- SM3 哈希 (中国国密标准)
- RC4 流密码加密
- 自定义 Base64 编码
- 时间戳/环境指纹拼接

纯标准库实现 (random/struct/time)，无第三方依赖。

使用方式:
    from app.services.fanqie_abogus import generate_a_bogus
    sig = generate_a_bogus("app_id=2503&rank_list_type=3&...", USER_AGENT)

背景:
    番茄 rank API 当前并未强制 a_bogus 校验，但字节跳动反爬策略每季度轮换。
    本模块作为前置防御: 一旦番茄重新开启强校验，无需紧急修复即可继续工作。
"""

import random
import struct
import time

# ─── RC4 Stream Cipher ────────────────────────────────────────────────

def rc4_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """RC4 流密码加密"""
    s = list(range(256))
    key_bytes = list(key)
    j = 0
    for i in range(256):
        j = (j + s[i] + key_bytes[i % len(key_bytes)]) & 0xFF
        s[i], s[j] = s[j], s[i]

    ii = 0
    jj = 0
    result = bytearray(len(plaintext))
    for n, byte in enumerate(plaintext):
        ii = (ii + 1) & 0xFF
        jj = (jj + s[ii]) & 0xFF
        s[ii], s[jj] = s[jj], s[ii]
        t = (s[ii] + s[jj]) & 0xFF
        result[n] = s[t] ^ byte
    return bytes(result)


# ─── SM3 Hash ─────────────────────────────────────────────────────────

def _left_rotate(x: int, n: int) -> int:
    """32-bit 循环左移"""
    n = n % 32
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _sm3_ffj(j: int, x: int, y: int, z: int) -> int:
    """SM3 布尔函数 FFj"""
    if j < 16:
        return x ^ y ^ z
    else:
        return (x & y) | (x & z) | (y & z)


def _sm3_ggj(j: int, x: int, y: int, z: int) -> int:
    """SM3 布尔函数 GGj"""
    if j < 16:
        return x ^ y ^ z
    else:
        return (x & y) | (~x & z & 0xFFFFFFFF)


def _sm3_tj(j: int) -> int:
    """SM3 常量 Tj"""
    if j < 16:
        return 0x79CC4519
    else:
        return 0x7A879D8A


def _sm3_p0(x: int) -> int:
    """SM3 置换函数 P0"""
    return x ^ _left_rotate(x, 9) ^ _left_rotate(x, 17)


def _sm3_p1(x: int) -> int:
    """SM3 置换函数 P1"""
    return x ^ _left_rotate(x, 15) ^ _left_rotate(x, 23)


def _sm3_compress_block(reg: list, block: bytes) -> list:
    """SM3 消息压缩函数，处理一个 64 字节块"""
    w = [0] * 132

    # 消息扩展：W0 ~ W15
    for i in range(16):
        w[i] = struct.unpack_from(">I", block, 4 * i)[0]

    # 消息扩展：W16 ~ W67
    for n in range(16, 68):
        a = w[n - 16] ^ w[n - 9] ^ _left_rotate(w[n - 3], 15)
        a = a ^ _left_rotate(a, 15) ^ _left_rotate(a, 23)
        w[n] = a ^ _left_rotate(w[n - 13], 7) ^ w[n - 6]

    # 消息扩展：W'0 ~ W'63
    for n in range(64):
        w[n + 68] = w[n] ^ w[n + 4]

    # 64 轮压缩
    v = list(reg)
    for c in range(64):
        ss1 = (_left_rotate(v[0], 12) + v[4] + _left_rotate(_sm3_tj(c), c)) & 0xFFFFFFFF
        ss1 = _left_rotate(ss1, 7) ^ _left_rotate(v[0], 12)
        tt1 = (_sm3_ffj(c, v[0], v[1], v[2]) + v[3] + ss1 + w[c + 68]) & 0xFFFFFFFF
        tt2 = (_sm3_ggj(c, v[4], v[5], v[6]) + v[7] + (ss1 + _left_rotate(v[0], 12)) + w[c]) & 0xFFFFFFFF
        v[3] = v[2]
        v[2] = _left_rotate(v[1], 9)
        v[1] = v[0]
        v[0] = tt1
        v[7] = v[6]
        v[6] = _left_rotate(v[5], 19)
        v[5] = v[4]
        v[4] = _sm3_p0(tt2)

    result = list(reg)
    for i in range(8):
        result[i] ^= v[i]
    return result


def _reg_to_bytes(reg: list) -> bytes:
    """将 SM3 寄存器值转为 32 字节"""
    return struct.pack(">8I", *reg)


class SM3:
    """SM3 哈希算法（国密标准）"""

    IV = [
        0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
        0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E,
    ]

    def __init__(self):
        self.reg = list(self.IV)
        self.chunk = bytearray()
        self.size = 0

    def reset(self):
        self.reg = list(self.IV)
        self.chunk = bytearray()
        self.size = 0

    def _url_encode_bytes(self, s: str) -> bytes:
        """URL 编码（保留字母数字和 -_.~ 空格，其余百分号编码）

        等效于 Rust 中的 url_encode_bytes:
        字母数字字符和 " -_.~" 中的字符保持不变，其他字符进行百分号编码。
        """
        result = bytearray()
        safe = b" -_.~"
        hex_chars = b"0123456789ABCDEF"
        for ch in s.encode('utf-8'):
            if (48 <= ch <= 57) or (65 <= ch <= 90) or (97 <= ch <= 122) or ch in safe:
                result.append(ch)
            else:
                result.append(ord('%'))
                result.append(hex_chars[ch >> 4])
                result.append(hex_chars[ch & 0x0F])
        return bytes(result)

    def write_str(self, s: str):
        """写入字符串（先 URL 编码再作为字节写入）"""
        self.write_bytes(self._url_encode_bytes(s))

    def write_bytes(self, data: bytes):
        """写入原始字节"""
        self.size += len(data)
        if len(self.chunk) + len(data) < 64:
            self.chunk.extend(data)
            return

        # 填满当前块
        fill = 64 - len(self.chunk)
        self.chunk.extend(data[:fill])
        self.reg = _sm3_compress_block(self.reg, bytes(self.chunk))
        self.chunk.clear()

        offset = fill
        while offset + 64 <= len(data):
            self.reg = _sm3_compress_block(self.reg, data[offset:offset + 64])
            offset += 64

        if offset < len(data):
            self.chunk.extend(data[offset:])

    def write_u8_array(self, data: bytes):
        """写入字节数组（与 write_bytes 相同）"""
        self.write_bytes(data)

    def _fill(self):
        """SM3 填充（追加 1 bit + 填充 0 + 64-bit 长度）"""
        bit_len = 8 * self.size
        self.chunk.append(0x80)
        while len(self.chunk) % 64 < 56:
            self.chunk.append(0)
        # 追加 64-bit 大端长度
        hi = (bit_len >> 32) & 0xFFFFFFFF
        lo = bit_len & 0xFFFFFFFF
        self.chunk.extend(struct.pack(">II", hi, lo))

    def sum_hex(self, s: str) -> str:
        """计算字符串的 SM3 哈希（十六进制）"""
        self.reset()
        self.write_str(s)
        self._fill()
        for i in range(0, len(self.chunk), 64):
            chunk = bytes(self.chunk[i:i + 64])
            if len(chunk) == 64:
                self.reg = _sm3_compress_block(self.reg, chunk)
        result = "".join(f"{r:08x}" for r in self.reg)
        self.reset()
        return result

    def sum_bytes(self, s: str) -> bytes:
        """计算字符串的 SM3 哈希（32 字节）"""
        self.reset()
        self.write_str(s)
        self._fill()
        for i in range(0, len(self.chunk), 64):
            chunk = bytes(self.chunk[i:i + 64])
            if len(chunk) == 64:
                self.reg = _sm3_compress_block(self.reg, chunk)
        result = _reg_to_bytes(self.reg)
        self.reset()
        return result

    def sum_bytes_from_bytes(self, data: bytes) -> bytes:
        """计算字节数组的 SM3 哈希（32 字节）"""
        self.reset()
        self.write_u8_array(data)
        self._fill()
        for i in range(0, len(self.chunk), 64):
            chunk = bytes(self.chunk[i:i + 64])
            if len(chunk) == 64:
                self.reg = _sm3_compress_block(self.reg, chunk)
        result = _reg_to_bytes(self.reg)
        self.reset()
        return result


# ─── 自定义 Base64 编码 ───────────────────────────────────────────────

_ENCODE_TABLES = {
    "s0": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=",
    "s1": "Dkdpgh4ZKsQB80/Mfvw36XI1R25+WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
    "s2": "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
    "s3": "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe",
    "s4": "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe",
}


def result_encrypt(data: bytes, table_name: str) -> str:
    """自定义 Base64 编码（3 字节 → 4 字符）"""
    table = _ENCODE_TABLES.get(table_name, _ENCODE_TABLES["s0"])
    masks = [0xFC0000, 0x03F000, 0x000FC0]  # 提取 4 组 6-bit

    result = []
    chunks = len(data) // 3
    for round_idx in range(chunks):
        r = round_idx * 3
        long_int = (data[r] << 16) | (data[r + 1] << 8) | data[r + 2]
        temp = [
            (long_int & masks[0]) >> 18,
            (long_int & masks[1]) >> 12,
            (long_int & masks[2]) >> 6,
            long_int & 63,
        ]
        result.extend(table[t] for t in temp)

    return "".join(result)


# ─── 随机字符串生成 ────────────────────────────────────────────────────

def _gener_random(random_val: int, option: tuple) -> bytes:
    """生成 4 字节随机数据"""
    return bytes([
        ((random_val & 0xFF & 0xAA) | (option[0] & 0x55)),
        ((random_val & 0xFF & 0x55) | (option[0] & 0xAA)),
        (((random_val >> 8) & 0xFF & 0xAA) | (option[1] & 0x55)),
        (((random_val >> 8) & 0xFF & 0x55) | (option[1] & 0xAA)),
    ])


def _generate_random_str() -> bytes:
    """生成 12 字节随机字符串"""
    result = bytearray()
    r1 = int(random.random() * 10000)
    result.extend(_gener_random(r1, (3, 45)))
    r2 = int(random.random() * 10000)
    result.extend(_gener_random(r2, (1, 0)))
    r3 = int(random.random() * 10000)
    result.extend(_gener_random(r3, (1, 5)))
    return bytes(result)


# ─── RC4 加密的二进制 blob 构造 ──────────────────────────────────────

WINDOW_ENV_STR = "1536|747|1536|834|0|30|0|0|1536|834|1536|864|1525|747|24|24|Win32"


def _generate_rc4_bb_str(url_search_params: str, user_agent: str) -> bytes:
    """构造 RC4 加密的二进制 blob"""
    sm3 = SM3()

    start_time_ms = int(time.time() * 1000) & 0xFFFFFFFF

    # SM3 哈希 URL 参数
    url_hash_hex = sm3.sum_hex(url_search_params)
    url_search_params_list = sm3.sum_bytes(url_hash_hex)

    # SM3 哈希后缀 "cus"
    cus_hash_hex = sm3.sum_hex("cus")
    cus_list = sm3.sum_bytes(cus_hash_hex)

    # RC4 加密 UA + 编码 + 哈希
    rc4_key = bytes([0x01, 0x00, 0x0E])
    ua_bytes = user_agent.encode('latin-1')
    rc4_encrypted_ua = rc4_encrypt(ua_bytes, rc4_key)
    ua_base64 = result_encrypt(rc4_encrypted_ua, "s3")
    ua_list = sm3.sum_bytes_from_bytes(ua_base64.encode('latin-1'))

    end_time_ms = int(time.time() * 1000) & 0xFFFFFFFF

    # 构造 b 字典（u32 值，用于构建 blob）
    b = {}
    b[8] = 3
    b[10] = end_time_ms
    b[16] = start_time_ms
    b[18] = 44

    b[20] = (b[16] >> 24) & 0xFF
    b[21] = (b[16] >> 16) & 0xFF
    b[22] = (b[16] >> 8) & 0xFF
    b[23] = b[16] & 0xFF
    b[24] = 0
    b[25] = 0

    # args = (0, 1, 14)
    b[26] = 0
    b[27] = 0
    b[28] = 0
    b[29] = 0

    b[30] = 0
    b[31] = 1
    b[32] = 0
    b[33] = 0
    b[34] = 0
    b[35] = 0
    b[36] = 0
    b[37] = 14

    # URL 哈希的第 22/23 字节
    b[38] = url_search_params_list[21]
    b[39] = url_search_params_list[22]

    # cus 哈希的第 22/23 字节
    b[40] = cus_list[21]
    b[41] = cus_list[22]

    # UA 哈希的第 24/25 字节
    b[42] = ua_list[23]
    b[43] = ua_list[24]

    # 结束时间戳
    b[44] = (b[10] >> 24) & 0xFF
    b[45] = (b[10] >> 16) & 0xFF
    b[46] = (b[10] >> 8) & 0xFF
    b[47] = b[10] & 0xFF
    b[48] = b[8]
    b[49] = 0
    b[50] = 0

    # page_id 和 aid
    page_id = 6241
    aid = 6383

    b[51] = page_id
    b[52] = (page_id >> 24) & 0xFF
    b[53] = (page_id >> 16) & 0xFF
    b[54] = (page_id >> 8) & 0xFF
    b[55] = page_id & 0xFF

    b[56] = aid
    b[57] = aid & 0xFF
    b[58] = (aid >> 8) & 0xFF
    b[59] = (aid >> 16) & 0xFF
    b[60] = (aid >> 24) & 0xFF

    # 窗口环境字符串长度
    window_env_bytes = WINDOW_ENV_STR.encode('latin-1')
    env_len = len(window_env_bytes)
    b[64] = env_len
    b[65] = env_len & 0xFF
    b[66] = (env_len >> 8) & 0xFF

    b[69] = 0
    b[70] = 0
    b[71] = 0

    # 校验和
    b[72] = (
        b[18] ^ b[20] ^ b[26] ^ b[30] ^ b[38] ^ b[40] ^ b[42]
        ^ b[21] ^ b[27] ^ b[31] ^ b[35] ^ b[39] ^ b[41] ^ b[43]
        ^ b[22] ^ b[28] ^ b[32] ^ b[36]
        ^ b[23] ^ b[29] ^ b[33] ^ b[37]
        ^ b[44] ^ b[45] ^ b[46] ^ b[47] ^ b[48] ^ b[49] ^ b[50]
        ^ b[24] ^ b[25]
        ^ b[52] ^ b[53] ^ b[54] ^ b[55]
        ^ b[57] ^ b[58] ^ b[59] ^ b[60]
        ^ b[65] ^ b[66]
        ^ b[70] ^ b[71]
    )

    # 按顺序输出 blob
    bb_order = [
        18, 20, 52, 26, 30, 34, 58, 38, 40, 53, 42, 21, 27, 54, 55, 31,
        35, 57, 39, 41, 43, 22, 28, 32, 60, 36, 23, 29, 33, 37, 44, 45,
        59, 46, 47, 48, 49, 50, 24, 25, 65, 66, 70, 71,
    ]

    bb = bytearray()
    for idx in bb_order:
        bb.append(b.get(idx, 0) & 0xFF)
    bb.extend(window_env_bytes)
    bb.append(b[72] & 0xFF)

    # Rust 中 String::from_utf8_lossy → .bytes() 的等效：UTF-8 解码含替换字符再编码
    bb_str = bytes(bb).decode('utf-8', errors='replace')
    bb_utf8 = bb_str.encode('utf-8')

    return rc4_encrypt(bb_utf8, bytes([121]))


# ─── 主入口 ───────────────────────────────────────────────────────────

def generate_a_bogus(url_search_params: str, user_agent: str) -> str:
    """生成 a_bogus 反爬签名

    Args:
        url_search_params: URL 查询参数字符串（不含 ?，未做 URL 编码）
        user_agent: 请求使用的 User-Agent

    Returns:
        a_bogus 签名字符串（可直接拼到 URL 末尾，调用方需自行 URL 编码）
    """
    random_str = _generate_random_str()
    rc4_bb = _generate_rc4_bb_str(url_search_params, user_agent)

    combined = bytearray(random_str)
    combined.extend(rc4_bb)

    return result_encrypt(bytes(combined), "s4") + "="
