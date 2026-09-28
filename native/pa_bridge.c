/*
 * pa_bridge.dll -- Prison Architect agent bridge (GLU32 proxy).
 *
 * Loaded by the game as GLU32.dll from the game folder. It forwards the six
 * GLU functions the game uses to the real system glu32.dll, then:
 *
 *   1. Replaces the game's Lua C function Game.DebugOut (0x14046D540) with
 *      bridge_debugout(). Every script's Game.DebugOut / print now reaches us.
 *   2. Runs a TCP server on 127.0.0.1:8972 (JSON lines, opaque to this DLL).
 *
 * Channel with the in-game Lua runtime (mod world.lua):
 *   Game.DebugOut("\1hello:<ver>")  -> returns "pa_bridge <ver>"
 *   Game.DebugOut("\1poll")         -> returns next request line, or nothing
 *   Game.DebugOut("\1reply:<json>") -> <json> is sent to the client
 *   anything else                   -> treated as print(); sent as a log event
 *
 * The DLL checks the exact exe bytes before patching and does nothing on a
 * mismatch (other game builds), apart from forwarding GLU.
 *
 * Freestanding: no CRT, no Windows SDK headers.
 */

typedef unsigned long long u64;
typedef long long i64;
typedef unsigned int u32;
typedef int i32;
typedef unsigned short u16;
typedef unsigned char u8;
typedef u64 size_t;
typedef void *HANDLE;
typedef int BOOL;
typedef u64 SOCKET;

#define IMPORT __declspec(dllimport)
#define INVALID_SOCKET ((SOCKET)~0ULL)

/* ---- kernel32 ---- */
IMPORT void *__stdcall LoadLibraryA(const char *);
IMPORT void *__stdcall GetProcAddress(void *, const char *);
IMPORT u32 __stdcall GetSystemDirectoryA(char *, u32);
IMPORT BOOL __stdcall VirtualProtect(void *, size_t, u32, u32 *);
IMPORT BOOL __stdcall FlushInstructionCache(HANDLE, const void *, size_t);
IMPORT HANDLE __stdcall GetCurrentProcess(void);
IMPORT HANDLE __stdcall CreateThread(void *, size_t, u32(__stdcall *)(void *), void *, u32, u32 *);
IMPORT void __stdcall InitializeCriticalSection(void *);
IMPORT void __stdcall EnterCriticalSection(void *);
IMPORT void __stdcall LeaveCriticalSection(void *);
IMPORT HANDLE __stdcall GetProcessHeap(void);
IMPORT void *__stdcall HeapAlloc(HANDLE, u32, size_t);
IMPORT BOOL __stdcall HeapFree(HANDLE, u32, void *);
IMPORT u64 __stdcall GetTickCount64(void);
IMPORT void __stdcall Sleep(u32);
IMPORT u32 __stdcall GetEnvironmentVariableA(const char *, char *, u32);
IMPORT HANDLE __stdcall CreateFileA(const char *, u32, u32, void *, u32, u32, HANDLE);
IMPORT BOOL __stdcall WriteFile(HANDLE, const void *, u32, u32 *, void *);
IMPORT BOOL __stdcall DisableThreadLibraryCalls(void *);

/* ---- ws2_32 ---- */
struct sockaddr_in { u16 sin_family; u16 sin_port; u32 sin_addr; char zero[8]; };
struct timeval { i32 tv_sec; i32 tv_usec; };
typedef struct { u32 fd_count; SOCKET fd_array[64]; } fd_set;
IMPORT i32 __stdcall WSAStartup(u16, void *);
IMPORT SOCKET __stdcall socket(i32, i32, i32);
IMPORT i32 __stdcall bind(SOCKET, const void *, i32);
IMPORT i32 __stdcall listen(SOCKET, i32);
IMPORT SOCKET __stdcall accept(SOCKET, void *, i32 *);
IMPORT i32 __stdcall recv(SOCKET, char *, i32, i32);
IMPORT i32 __stdcall send(SOCKET, const char *, i32, i32);
IMPORT i32 __stdcall closesocket(SOCKET);
IMPORT i32 __stdcall select(i32, fd_set *, fd_set *, fd_set *, const struct timeval *);
IMPORT i32 __stdcall setsockopt(SOCKET, i32, i32, const char *, i32);

/* ---- tiny libc ---- */
void *memcpy(void *d, const void *s, size_t n) { u8 *a = d; const u8 *b = s; while (n--) *a++ = *b++; return d; }
void *memset(void *d, int c, size_t n) { u8 *a = d; while (n--) *a++ = (u8)c; return d; }
void *memmove(void *d, const void *s, size_t n) {
    u8 *a = d; const u8 *b = s;
    if (a < b) { while (n--) *a++ = *b++; } else { a += n; b += n; while (n--) *--a = *--b; }
    return d;
}
static size_t slen(const char *s) { size_t n = 0; while (s[n]) n++; return n; }
static int starts(const char *s, size_t n, const char *p) {
    size_t m = slen(p); if (n < m) return 0;
    for (size_t i = 0; i < m; i++) if (s[i] != p[i]) return 0;
    return 1;
}
int _fltused = 0;

#define BRIDGE_VERSION "0.2.1"
#define PORT 8972

/* ================= GLU forwarding =================
 * Export every function of the system glu32.dll (52), not only the 6 the game
 * uses: other DLLs in the process (e.g. OpenGL drivers) that load "glu32.dll"
 * by name get this file too, and a missing export stops the game at startup
 * with 0xC0000139 (entry point not found). */
#define GLU_COUNT 52
static const char *const glu_names[GLU_COUNT] = {
    "gluBeginCurve",
    "gluBeginPolygon",
    "gluBeginSurface",
    "gluBeginTrim",
    "gluBuild1DMipmaps",
    "gluBuild2DMipmaps",
    "gluCylinder",
    "gluDeleteNurbsRenderer",
    "gluDeleteQuadric",
    "gluDeleteTess",
    "gluDisk",
    "gluEndCurve",
    "gluEndPolygon",
    "gluEndSurface",
    "gluEndTrim",
    "gluErrorString",
    "gluErrorUnicodeStringEXT",
    "gluGetNurbsProperty",
    "gluGetString",
    "gluGetTessProperty",
    "gluLoadSamplingMatrices",
    "gluLookAt",
    "gluNewNurbsRenderer",
    "gluNewQuadric",
    "gluNewTess",
    "gluNextContour",
    "gluNurbsCallback",
    "gluNurbsCurve",
    "gluNurbsProperty",
    "gluNurbsSurface",
    "gluOrtho2D",
    "gluPartialDisk",
    "gluPerspective",
    "gluPickMatrix",
    "gluProject",
    "gluPwlCurve",
    "gluQuadricCallback",
    "gluQuadricDrawStyle",
    "gluQuadricNormals",
    "gluQuadricOrientation",
    "gluQuadricTexture",
    "gluScaleImage",
    "gluSphere",
    "gluTessBeginContour",
    "gluTessBeginPolygon",
    "gluTessCallback",
    "gluTessEndContour",
    "gluTessEndPolygon",
    "gluTessNormal",
    "gluTessProperty",
    "gluTessVertex",
    "gluUnProject"
};
void *glu_real[GLU_COUNT];

__asm__(
    ".intel_syntax noprefix\n"
    ".globl gluBeginCurve\n gluBeginCurve: jmp qword ptr [rip + glu_real + 0]\n"
    ".globl gluBeginPolygon\n gluBeginPolygon: jmp qword ptr [rip + glu_real + 8]\n"
    ".globl gluBeginSurface\n gluBeginSurface: jmp qword ptr [rip + glu_real + 16]\n"
    ".globl gluBeginTrim\n gluBeginTrim: jmp qword ptr [rip + glu_real + 24]\n"
    ".globl gluBuild1DMipmaps\n gluBuild1DMipmaps: jmp qword ptr [rip + glu_real + 32]\n"
    ".globl gluBuild2DMipmaps\n gluBuild2DMipmaps: jmp qword ptr [rip + glu_real + 40]\n"
    ".globl gluCylinder\n gluCylinder: jmp qword ptr [rip + glu_real + 48]\n"
    ".globl gluDeleteNurbsRenderer\n gluDeleteNurbsRenderer: jmp qword ptr [rip + glu_real + 56]\n"
    ".globl gluDeleteQuadric\n gluDeleteQuadric: jmp qword ptr [rip + glu_real + 64]\n"
    ".globl gluDeleteTess\n gluDeleteTess: jmp qword ptr [rip + glu_real + 72]\n"
    ".globl gluDisk\n gluDisk: jmp qword ptr [rip + glu_real + 80]\n"
    ".globl gluEndCurve\n gluEndCurve: jmp qword ptr [rip + glu_real + 88]\n"
    ".globl gluEndPolygon\n gluEndPolygon: jmp qword ptr [rip + glu_real + 96]\n"
    ".globl gluEndSurface\n gluEndSurface: jmp qword ptr [rip + glu_real + 104]\n"
    ".globl gluEndTrim\n gluEndTrim: jmp qword ptr [rip + glu_real + 112]\n"
    ".globl gluErrorString\n gluErrorString: jmp qword ptr [rip + glu_real + 120]\n"
    ".globl gluErrorUnicodeStringEXT\n gluErrorUnicodeStringEXT: jmp qword ptr [rip + glu_real + 128]\n"
    ".globl gluGetNurbsProperty\n gluGetNurbsProperty: jmp qword ptr [rip + glu_real + 136]\n"
    ".globl gluGetString\n gluGetString: jmp qword ptr [rip + glu_real + 144]\n"
    ".globl gluGetTessProperty\n gluGetTessProperty: jmp qword ptr [rip + glu_real + 152]\n"
    ".globl gluLoadSamplingMatrices\n gluLoadSamplingMatrices: jmp qword ptr [rip + glu_real + 160]\n"
    ".globl gluLookAt\n gluLookAt: jmp qword ptr [rip + glu_real + 168]\n"
    ".globl gluNewNurbsRenderer\n gluNewNurbsRenderer: jmp qword ptr [rip + glu_real + 176]\n"
    ".globl gluNewQuadric\n gluNewQuadric: jmp qword ptr [rip + glu_real + 184]\n"
    ".globl gluNewTess\n gluNewTess: jmp qword ptr [rip + glu_real + 192]\n"
    ".globl gluNextContour\n gluNextContour: jmp qword ptr [rip + glu_real + 200]\n"
    ".globl gluNurbsCallback\n gluNurbsCallback: jmp qword ptr [rip + glu_real + 208]\n"
    ".globl gluNurbsCurve\n gluNurbsCurve: jmp qword ptr [rip + glu_real + 216]\n"
    ".globl gluNurbsProperty\n gluNurbsProperty: jmp qword ptr [rip + glu_real + 224]\n"
    ".globl gluNurbsSurface\n gluNurbsSurface: jmp qword ptr [rip + glu_real + 232]\n"
    ".globl gluOrtho2D\n gluOrtho2D: jmp qword ptr [rip + glu_real + 240]\n"
    ".globl gluPartialDisk\n gluPartialDisk: jmp qword ptr [rip + glu_real + 248]\n"
    ".globl gluPerspective\n gluPerspective: jmp qword ptr [rip + glu_real + 256]\n"
    ".globl gluPickMatrix\n gluPickMatrix: jmp qword ptr [rip + glu_real + 264]\n"
    ".globl gluProject\n gluProject: jmp qword ptr [rip + glu_real + 272]\n"
    ".globl gluPwlCurve\n gluPwlCurve: jmp qword ptr [rip + glu_real + 280]\n"
    ".globl gluQuadricCallback\n gluQuadricCallback: jmp qword ptr [rip + glu_real + 288]\n"
    ".globl gluQuadricDrawStyle\n gluQuadricDrawStyle: jmp qword ptr [rip + glu_real + 296]\n"
    ".globl gluQuadricNormals\n gluQuadricNormals: jmp qword ptr [rip + glu_real + 304]\n"
    ".globl gluQuadricOrientation\n gluQuadricOrientation: jmp qword ptr [rip + glu_real + 312]\n"
    ".globl gluQuadricTexture\n gluQuadricTexture: jmp qword ptr [rip + glu_real + 320]\n"
    ".globl gluScaleImage\n gluScaleImage: jmp qword ptr [rip + glu_real + 328]\n"
    ".globl gluSphere\n gluSphere: jmp qword ptr [rip + glu_real + 336]\n"
    ".globl gluTessBeginContour\n gluTessBeginContour: jmp qword ptr [rip + glu_real + 344]\n"
    ".globl gluTessBeginPolygon\n gluTessBeginPolygon: jmp qword ptr [rip + glu_real + 352]\n"
    ".globl gluTessCallback\n gluTessCallback: jmp qword ptr [rip + glu_real + 360]\n"
    ".globl gluTessEndContour\n gluTessEndContour: jmp qword ptr [rip + glu_real + 368]\n"
    ".globl gluTessEndPolygon\n gluTessEndPolygon: jmp qword ptr [rip + glu_real + 376]\n"
    ".globl gluTessNormal\n gluTessNormal: jmp qword ptr [rip + glu_real + 384]\n"
    ".globl gluTessProperty\n gluTessProperty: jmp qword ptr [rip + glu_real + 392]\n"
    ".globl gluTessVertex\n gluTessVertex: jmp qword ptr [rip + glu_real + 400]\n"
    ".globl gluUnProject\n gluUnProject: jmp qword ptr [rip + glu_real + 408]\n"
    ".att_syntax\n");

static int load_real_glu(void) {
    char path[300];
    u32 n = GetSystemDirectoryA(path, 260);
    if (!n || n > 260) return 0;
    memcpy(path + n, "\\glu32.dll", 11);
    void *m = LoadLibraryA(path);
    if (!m) return 0;
    int missing = 0;
    for (int i = 0; i < GLU_COUNT; i++) {
        glu_real[i] = GetProcAddress(m, glu_names[i]);
        if (!glu_real[i]) missing++;
    }
    return glu_real[5] && glu_real[21] && missing < GLU_COUNT;
}

/* ================= logging ================= */
static HANDLE g_log = 0;
static void log_open(void) {
    char path[400];
    u32 n = GetEnvironmentVariableA("LOCALAPPDATA", path, 300);
    if (!n || n > 300) return;
    const char *tail = "\\Introversion\\Prison Architect\\pa_bridge.log";
    memcpy(path + n, tail, slen(tail) + 1);
    /* GENERIC_WRITE, FILE_SHARE_READ|WRITE, CREATE_ALWAYS, NORMAL */
    g_log = CreateFileA(path, 0x40000000, 3, 0, 2, 0x80, 0);
    if (g_log == (HANDLE)(i64)-1) g_log = 0;
}
static void logw(const char *s, size_t n) { u32 w; if (g_log) WriteFile(g_log, s, (u32)n, &w, 0); }
static void logs(const char *s) { logw(s, slen(s)); }
static void loghex(u64 v) {
    char b[19]; b[0] = '0'; b[1] = 'x';
    for (int i = 0; i < 16; i++) { int d = (v >> (60 - 4 * i)) & 15; b[2 + i] = (char)(d < 10 ? '0' + d : 'a' + d - 10); }
    logw(b, 18);
}

/* ================= byte queues (lines) ================= */
typedef struct { char *buf; size_t len, cap; } bytes_t;
static u8 g_lock[64]; /* CRITICAL_SECTION is 40 bytes on x64 */
static bytes_t g_inbox, g_outbox;
static u64 g_last_poll = 0;
static int g_lua_hello = 0;
static int g_patched = 0;
static int g_client = 0;

static int bytes_push(bytes_t *q, const char *s, size_t n) {
    if (q->len + n > q->cap) {
        size_t nc = q->cap ? q->cap : 65536;
        while (nc < q->len + n) nc *= 2;
        if (nc > (256u << 20)) return 0; /* 256 MB safety cap */
        char *nb = HeapAlloc(GetProcessHeap(), 0, nc);
        if (!nb) return 0;
        if (q->buf) { memcpy(nb, q->buf, q->len); HeapFree(GetProcessHeap(), 0, q->buf); }
        q->buf = nb; q->cap = nc;
    }
    memcpy(q->buf + q->len, s, n); q->len += n;
    return 1;
}
static void bytes_consume(bytes_t *q, size_t n) {
    if (n >= q->len) { q->len = 0; return; }
    memmove(q->buf, q->buf + n, q->len - n); q->len -= n;
}

static void out_line(const char *s, size_t n) {
    EnterCriticalSection(g_lock);
    if (g_client) { bytes_push(&g_outbox, s, n); bytes_push(&g_outbox, "\n", 1); }
    LeaveCriticalSection(g_lock);
}

/* JSON-escape into the outbox as {"type":"log","msg":"..."} */
static void out_log(const char *s, size_t n) {
    static const char hex[] = "0123456789abcdef";
    EnterCriticalSection(g_lock);
    if (g_client) {
        bytes_push(&g_outbox, "{\"type\":\"log\",\"msg\":\"", 21);
        for (size_t i = 0; i < n; i++) {
            u8 c = (u8)s[i];
            if (c == '"' || c == '\\') { char e[2] = {'\\', (char)c}; bytes_push(&g_outbox, e, 2); }
            else if (c < 0x20) { char e[6] = {'\\', 'u', '0', '0', hex[c >> 4], hex[c & 15]}; bytes_push(&g_outbox, e, 6); }
            else bytes_push(&g_outbox, (const char *)&c, 1);
        }
        bytes_push(&g_outbox, "\"}\n", 3);
    }
    LeaveCriticalSection(g_lock);
}

/* ================= Lua glue (Prison Architect build r11056, Feb 24 2023) ================= */
/* Lua 5.1 lua_State: top at +0x10, base at +0x18. TValue = 16 bytes: value @0, tt @8.
   TString: len @+0x10, chars @+0x18. LUA_TSTRING = 4. */
typedef void (*lua_pushlstring_t)(void *L, const char *s, size_t len);
static const lua_pushlstring_t lua_pushlstring = (lua_pushlstring_t)0x1407fe3e0ULL;

#define DEBUGOUT_ADDR 0x14046d540ULL
static const u8 DEBUGOUT_EXPECT[15] = {0x40, 0x53, 0x48, 0x83, 0xEC, 0x70, 0x48, 0xC7, 0x44, 0x24, 0x20, 0xFE, 0xFF, 0xFF, 0xFF};
static const u8 PUSHLSTRING_EXPECT[8] = {0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x6C};

static int arg_string(void *L, int idx, const char **s, size_t *n) {
    u8 *base = *(u8 **)((u8 *)L + 0x18);
    u8 *top = *(u8 **)((u8 *)L + 0x10);
    if (base + 16 * (idx + 1) > top) return 0;
    u8 *tv = base + 16 * idx;
    if (*(i32 *)(tv + 8) != 4) return 0;
    u8 *ts = *(u8 **)tv;
    *n = *(size_t *)(ts + 0x10);
    *s = (const char *)(ts + 0x18);
    return 1;
}

static int __cdecl bridge_debugout(void *L) {
    const char *s; size_t n;
    if (!arg_string(L, 0, &s, &n)) return 0;
    if (n >= 1 && s[0] == 1) {
        s++; n--;
        if (starts(s, n, "poll")) {
            g_last_poll = GetTickCount64();
            char *line = 0; size_t ln = 0;
            EnterCriticalSection(g_lock);
            for (size_t i = 0; i < g_inbox.len; i++) {
                if (g_inbox.buf[i] == '\n') {
                    line = HeapAlloc(GetProcessHeap(), 0, i + 1);
                    if (line) { memcpy(line, g_inbox.buf, i); ln = i; }
                    bytes_consume(&g_inbox, i + 1);
                    break;
                }
            }
            LeaveCriticalSection(g_lock);
            if (!line) return 0;
            lua_pushlstring(L, line, ln);
            HeapFree(GetProcessHeap(), 0, line);
            return 1;
        }
        if (starts(s, n, "reply:")) { out_line(s + 6, n - 6); return 0; }
        if (starts(s, n, "hello:")) {
            g_lua_hello = 1;
            g_last_poll = GetTickCount64();
            logs("lua runtime hello: "); logw(s + 6, n - 6); logs("\r\n");
            const char *v = "pa_bridge " BRIDGE_VERSION;
            lua_pushlstring(L, v, slen(v));
            return 1;
        }
        return 0;
    }
    out_log(s, n);
    return 0;
}

static int patch_debugout(void) {
    u8 *p = (u8 *)DEBUGOUT_ADDR;
    for (int i = 0; i < 15; i++) if (p[i] != DEBUGOUT_EXPECT[i]) { logs("DebugOut bytes mismatch; not patching\r\n"); return 0; }
    u8 *q = (u8 *)lua_pushlstring;
    for (int i = 0; i < 8; i++) if (q[i] != PUSHLSTRING_EXPECT[i]) { logs("pushlstring bytes mismatch; not patching\r\n"); return 0; }
    u8 stub[12] = {0x48, 0xB8, 0, 0, 0, 0, 0, 0, 0, 0, 0xFF, 0xE0}; /* mov rax, imm64; jmp rax */
    u64 target = (u64)(void *)bridge_debugout;
    memcpy(stub + 2, &target, 8);
    u32 old;
    if (!VirtualProtect(p, 12, 0x40, &old)) { logs("VirtualProtect failed\r\n"); return 0; }
    memcpy(p, stub, 12);
    VirtualProtect(p, 12, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, 12);
    logs("patched Game.DebugOut -> "); loghex(target); logs("\r\n");
    return 1;
}

/* ================= TCP server ================= */
static void status_line(SOCKET c) {
    char b[256]; size_t k = 0;
    const char *a = "{\"type\":\"status\",\"bridge\":\"" BRIDGE_VERSION "\",\"patched\":";
    memcpy(b, a, slen(a)); k = slen(a);
    b[k++] = g_patched ? 't' : 'f';
    const char *t = g_patched ? "rue" : "alse"; memcpy(b + k, t, slen(t)); k += slen(t);
    const char *h = ",\"lua_seen\":"; memcpy(b + k, h, slen(h)); k += slen(h);
    b[k++] = g_lua_hello ? '1' : '0';
    const char *m = ",\"ms_since_poll\":"; memcpy(b + k, m, slen(m)); k += slen(m);
    u64 age = g_last_poll ? GetTickCount64() - g_last_poll : 0xFFFFFFFFULL;
    char d[24]; int dn = 0; if (!age) d[dn++] = '0'; while (age) { d[dn++] = (char)('0' + age % 10); age /= 10; }
    while (dn) b[k++] = d[--dn];
    b[k++] = '}'; b[k++] = '\n';
    send(c, b, (i32)k, 0);
}

static u32 __stdcall server_thread(void *arg) {
    (void)arg;
    u8 wsa[512];
    if (WSAStartup(0x0202, wsa) != 0) { logs("WSAStartup failed\r\n"); return 0; }
    SOCKET ls = socket(2, 1, 6);
    if (ls == INVALID_SOCKET) { logs("socket failed\r\n"); return 0; }
    struct sockaddr_in sa; memset(&sa, 0, sizeof sa);
    sa.sin_family = 2;
    sa.sin_port = (u16)((PORT >> 8) | ((PORT & 0xff) << 8));
    sa.sin_addr = 0x0100007F; /* 127.0.0.1 */
    int excl = 1; setsockopt(ls, 0xffff, ~4 /* SO_EXCLUSIVEADDRUSE */, (const char *)&excl, 4);
    if (bind(ls, &sa, sizeof sa) != 0 || listen(ls, 4) != 0) { logs("bind/listen failed on 127.0.0.1:8972\r\n"); return 0; }
    logs("listening on 127.0.0.1:8972\r\n");
    char *rbuf = HeapAlloc(GetProcessHeap(), 0, 65536);
    for (;;) {
        SOCKET c = accept(ls, 0, 0);
        if (c == INVALID_SOCKET) { Sleep(100); continue; }
        logs("client connected\r\n");
        EnterCriticalSection(g_lock); g_client = 1; g_outbox.len = 0; LeaveCriticalSection(g_lock);
        status_line(c);
        bytes_t partial = {0, 0, 0};
        for (;;) {
            fd_set rs; rs.fd_count = 1; rs.fd_array[0] = c;
            struct timeval tv = {0, 15000};
            int r = select(0, &rs, 0, 0, &tv);
            if (r < 0) break;
            if (r > 0) {
                int got = recv(c, rbuf, 65536, 0);
                if (got <= 0) break;
                bytes_push(&partial, rbuf, (size_t)got);
                size_t start = 0;
                for (size_t i = 0; i < partial.len; i++) {
                    if (partial.buf[i] != '\n') continue;
                    size_t ln = i - start;
                    const char *line = partial.buf + start;
                    if (ln && line[ln - 1] == '\r') ln--;
                    if (ln == 6 && starts(line, ln, "STATUS")) status_line(c);
                    else if (ln) {
                        EnterCriticalSection(g_lock);
                        bytes_push(&g_inbox, line, ln); bytes_push(&g_inbox, "\n", 1);
                        LeaveCriticalSection(g_lock);
                    }
                    start = i + 1;
                }
                bytes_consume(&partial, start);
            }
            /* flush outbox */
            EnterCriticalSection(g_lock);
            size_t n = g_outbox.len;
            char *tmp = 0;
            if (n) { tmp = HeapAlloc(GetProcessHeap(), 0, n); if (tmp) { memcpy(tmp, g_outbox.buf, n); g_outbox.len = 0; } }
            LeaveCriticalSection(g_lock);
            if (tmp) {
                size_t off = 0; int bad = 0;
                while (off < n) { int s = send(c, tmp + off, (i32)(n - off), 0); if (s <= 0) { bad = 1; break; } off += (size_t)s; }
                HeapFree(GetProcessHeap(), 0, tmp);
                if (bad) break;
            }
        }
        EnterCriticalSection(g_lock); g_client = 0; g_outbox.len = 0; g_inbox.len = 0; LeaveCriticalSection(g_lock);
        if (partial.buf) HeapFree(GetProcessHeap(), 0, partial.buf);
        closesocket(c);
        logs("client disconnected\r\n");
    }
}

/* ================= entry ================= */
BOOL __stdcall DllMain(void *inst, u32 reason, void *reserved) {
    (void)reserved;
    if (reason != 1) return 1;
    DisableThreadLibraryCalls(inst);
    log_open();
    logs("pa_bridge " BRIDGE_VERSION " loaded\r\n");
    if (!load_real_glu()) { logs("failed to load system glu32.dll\r\n"); return 0; }
    InitializeCriticalSection(g_lock);
    g_patched = patch_debugout();
    CreateThread(0, 0, server_thread, 0, 0, 0);
    return 1;
}
