/*
 * pa_bridge.dll -- Prison Architect agent bridge (GLU32 proxy).
 *
 * Loaded by the game as GLU32.dll from the game folder. It forwards the six
 * GLU functions the game uses to the real system glu32.dll, then:
 *
 *   1. Replaces the game's Lua C function Game.DebugOut (0x14046D540) with
 *      bridge_debugout(). Every script's Game.DebugOut / print now reaches us.
 *   2. Runs a TCP server on 127.0.0.1:8972 (JSON lines, opaque to this DLL).
 *      Up to 8 clients at once; each reply goes back to the client whose
 *      request the Lua runtime polled last (requests are handled one at a time).
 *
 * Channel with the in-game Lua runtime (mod world.lua):
 *   Game.DebugOut("\1hello:<ver>", pump) -> returns "pa_bridge <ver>"; pump is
 *                                    a Lua function the DLL may call while paused
 *   Game.DebugOut("\1poll")         -> returns next request line, or nothing
 *   Game.DebugOut("\1reply:<json>") -> <json> is sent to the client
 *   Game.DebugOut("\1zone:<Type> x1 y1 x2 y2") -> "ok <id>" | "error: ..."
 *   Game.DebugOut("\1roomtypes")    -> "None,Cell,..."
 *   Game.DebugOut("\1speed")        -> number (0 = paused)
 *   Game.DebugOut("\1setspeed:<n>") -> "ok"
 *   Game.DebugOut("\1save:<name>")  -> "queued" (runs outside Lua) | "error: ..."
 *   Game.DebugOut("\1saveresult")   -> "" | "ok <path>" | "error: ..."
 *   Game.DebugOut("\1researchlist") -> "Name:desired:percent,..."
 *   Game.DebugOut("\1research:<Name>") -> "ok" | "error: ..." (game charges the cost)
 *   Game.DebugOut("\1screenshot")   -> "queued"; the next rendered frame (the image the
 *                                    player last saw) is written to
 *                                    %LOCALAPPDATA%\Introversion\Prison Architect\pa_bridge_screenshot.bmp
 *   Game.DebugOut("\1screenshotresult") -> "pending" | "ok <path>" | "error: ..."
 *   Game.DebugOut("\1regime[:cat]") -> 24 activity names (cat 0 = base schedule)
 *   Game.DebugOut("\1setregime:<cat> <hour> <activity>") -> "ok"
 *   Game.DebugOut("\1camera[:x y [zoom]]") -> "x y zoom" (zoom = cells per pixel)
 *   Game.DebugOut("\1rmcable:x y") / ("\1rmpipe:x y") -> "ok" (removes that utility cell)
 *   Game.DebugOut("\1spend:<amount> <label>") -> "ok" (finance ledger entry)
 *   Game.DebugOut("\1intake")       -> "<type> <total> <perday>"
 *   Game.DebugOut("\1intake:<type> [n]") -> sets it (0 none, 1 free beds, 2 max total n, 3 n per day, 4 all)
 *   anything else                   -> treated as print(); sent as a log event
 *
 * Native actions call the game's own code paths, found by disassembly of
 * r11056: zoning uses the handler behind Game.SetZoneRoom (0x1401ab5f0) without
 * the campaign command queue that crashes in sandbox; saving uses the writer
 * behind the Save menu (0x140188a90). The game speed is world+0x88.
 *
 * Paused game: world scripts only get Update() while the simulation runs. The
 * game calls gluPerspective/gluLookAt/gluUnProject from its render loop, so
 * those exports run frame_tick(), which calls the Lua pump when requests are
 * waiting and Update has not polled for 250 ms.
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
IMPORT BOOL __stdcall CloseHandle(HANDLE);
IMPORT BOOL __stdcall DisableThreadLibraryCalls(void *);
IMPORT u32 __stdcall GetCurrentThreadId(void);

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

#define BRIDGE_VERSION "0.5.0"
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
    ".globl gluNewNurbsRenderer\n gluNewNurbsRenderer: jmp qword ptr [rip + glu_real + 176]\n"
    ".globl gluNewQuadric\n gluNewQuadric: jmp qword ptr [rip + glu_real + 184]\n"
    ".globl gluNewTess\n gluNewTess: jmp qword ptr [rip + glu_real + 192]\n"
    ".globl gluNextContour\n gluNextContour: jmp qword ptr [rip + glu_real + 200]\n"
    ".globl gluNurbsCallback\n gluNurbsCallback: jmp qword ptr [rip + glu_real + 208]\n"
    ".globl gluNurbsCurve\n gluNurbsCurve: jmp qword ptr [rip + glu_real + 216]\n"
    ".globl gluNurbsProperty\n gluNurbsProperty: jmp qword ptr [rip + glu_real + 224]\n"
    ".globl gluNurbsSurface\n gluNurbsSurface: jmp qword ptr [rip + glu_real + 232]\n"
    ".globl gluPartialDisk\n gluPartialDisk: jmp qword ptr [rip + glu_real + 248]\n"
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
static void bytes_free(bytes_t *q) {
    if (q->buf) HeapFree(GetProcessHeap(), 0, q->buf);
    q->buf = 0; q->len = q->cap = 0;
}

/* ================= clients ================= */
#define MAX_CLIENTS 8
typedef struct { SOCKET s; int used; bytes_t out; } client_t;
static u8 g_lock[64]; /* CRITICAL_SECTION is 40 bytes on x64 */
static client_t g_clients[MAX_CLIENTS];
/* Inbox lines are "<slot digit><request json>\n". */
static bytes_t g_inbox;
static int g_cur_slot = -1;          /* client of the request Lua is handling */
static u64 g_last_poll = 0;          /* any poll */
static u64 g_last_update_poll = 0;   /* poll from the game's Update (simulation running) */
static int g_lua_hello = 0;
static int g_patched = 0;
static int g_native_ok = 0;          /* game functions for zone/save/pump verified */

static void out_line(const char *s, size_t n) {
    EnterCriticalSection(g_lock);
    int k = g_cur_slot;
    if (k >= 0 && g_clients[k].used) { bytes_push(&g_clients[k].out, s, n); bytes_push(&g_clients[k].out, "\n", 1); }
    LeaveCriticalSection(g_lock);
}

/* JSON-escape into every client's outbox as {"type":"log","msg":"..."} */
static void out_log(const char *s, size_t n) {
    static const char hex[] = "0123456789abcdef";
    EnterCriticalSection(g_lock);
    for (int k = 0; k < MAX_CLIENTS; k++) {
        if (!g_clients[k].used) continue;
        bytes_t *o = &g_clients[k].out;
        bytes_push(o, "{\"type\":\"log\",\"msg\":\"", 21);
        for (size_t i = 0; i < n; i++) {
            u8 c = (u8)s[i];
            if (c == '"' || c == '\\') { char e[2] = {'\\', (char)c}; bytes_push(o, e, 2); }
            else if (c < 0x20) { char e[6] = {'\\', 'u', '0', '0', hex[c >> 4], hex[c & 15]}; bytes_push(o, e, 6); }
            else bytes_push(o, (const char *)&c, 1);
        }
        bytes_push(o, "\"}\n", 3);
    }
    LeaveCriticalSection(g_lock);
}

/* drop queued requests of a client that went away (caller holds the lock) */
static void purge_inbox(int slot) {
    size_t w = 0, i = 0, start = 0;
    char *b = g_inbox.buf;
    for (i = 0; i < g_inbox.len; i++) {
        if (b[i] != '\n') continue;
        size_t ln = i + 1 - start;
        if (b[start] != (char)('0' + slot)) { memmove(b + w, b + start, ln); w += ln; }
        start = i + 1;
    }
    if (start < g_inbox.len) { memmove(b + w, b + start, g_inbox.len - start); w += g_inbox.len - start; }
    g_inbox.len = w;
}

/* ================= small formatting ================= */
typedef struct { char *p; size_t n, cap; } sbuf;
static void sb_put(sbuf *b, const char *s, size_t n) { for (size_t i = 0; i < n && b->n + 1 < b->cap; i++) b->p[b->n++] = s[i]; b->p[b->n] = 0; }
static void sb_str(sbuf *b, const char *s) { sb_put(b, s, slen(s)); }
static void sb_int(sbuf *b, i64 v) {
    char d[24]; int n = 0; u64 u = v < 0 ? (u64)(-v) : (u64)v;
    if (v < 0) sb_put(b, "-", 1);
    if (!u) d[n++] = '0';
    while (u) { d[n++] = (char)('0' + u % 10); u /= 10; }
    while (n) { n--; sb_put(b, &d[n], 1); }
}
static int parse_int(const char **s, const char *end, i32 *out) {
    const char *p = *s; int neg = 0; i64 v = 0; int any = 0;
    while (p < end && *p == ' ') p++;
    if (p < end && *p == '-') { neg = 1; p++; }
    while (p < end && *p >= '0' && *p <= '9') { v = v * 10 + (*p - '0'); p++; any = 1; if (v > 100000) return 0; }
    *s = p; *out = (i32)(neg ? -v : v);
    return any;
}

/* ================= Lua glue (Prison Architect build r11056, Feb 24 2023) ================= */
/* Lua 5.1 lua_State: top at +0x10, base at +0x18. TValue = 16 bytes: value @0, tt @8.
   TString: len @+0x10, chars @+0x18. LUA_TSTRING = 4, LUA_TFUNCTION = 6. */
typedef void (*lua_pushlstring_t)(void *L, const char *s, size_t len);
typedef void (*lua_pushnumber_t)(void *L, double n);
typedef void (*lua_getfield_t)(void *L, int idx, const char *k);
typedef void (*lua_setfield_t)(void *L, int idx, const char *k);
typedef int (*lua_pcall_t)(void *L, int nargs, int nresults, int errfunc);
typedef void (*lua_settop_t)(void *L, int idx);
static const lua_pushlstring_t lua_pushlstring = (lua_pushlstring_t)0x1407fe3e0ULL;
static const lua_pushnumber_t lua_pushnumber = (lua_pushnumber_t)0x1407fe3a0ULL;
static const lua_getfield_t lua_getfield = (lua_getfield_t)0x1407fe570ULL;
static const lua_setfield_t lua_setfield = (lua_setfield_t)0x1407fe750ULL;
static const lua_pcall_t lua_pcall = (lua_pcall_t)0x1407fead0ULL;
static const lua_settop_t lua_settop = (lua_settop_t)0x1407fdff0ULL;
#define LUA_REGISTRYINDEX (-10000)
#define PUMP_KEY "pa_bridge_pump"

/* Game internals */
#define APP_PTR ((u8 **)0x140d57900ULL)          /* app object; +0x198 = world */
#define USERDIR_STR ((u8 *)0x140d2e0e0ULL)       /* cached user data dir std::string */
#define ROOMTYPES_PTR ((u8 **)0x140deccf0ULL)    /* array of std::string, stride 0x20 */
#define ROOMTYPES_COUNT ((i32 *)0x140deccfcULL)
#define RESEARCH_PTR ((u8 **)0x140df8f60ULL)     /* entries, stride 0x80: Desired u8 @0x6c, Progress f32 @0x70 */
#define RESEARCH_COUNT ((i32 *)0x140df8f6cULL)
#define RESEARCH_NAMES ((u8 **)0x140df8f70ULL)   /* std::string names, stride 0x20 */
typedef void (*zone_handler_t)(void *unused, void *cmd);
typedef i32 (*name_lookup_t)(void *str);
typedef u8 (*save_map_t)(void *app, void *path, u8 temp, u8 b, u8 c);
typedef void (*start_research_t)(void *unused, i32 idx);
static const zone_handler_t zone_handler = (zone_handler_t)0x1401ab5f0ULL;
static const name_lookup_t roomtype_lookup = (name_lookup_t)0x14060a230ULL;
static const name_lookup_t research_lookup = (name_lookup_t)0x1406ecfc0ULL;
static const save_map_t save_map = (save_map_t)0x140188a90ULL;
/* sets Desired, charges the cost to the finance ledger ("research_<name>") */
static const start_research_t start_research = (start_research_t)0x1406ed2c0ULL;

/* MSVC std::string: 16-byte buffer or heap pointer, size @0x10, capacity @0x18 */
typedef struct { union { char buf[16]; char *ptr; } u; u64 size; u64 cap; } msstr;
static void msstr_ref(msstr *s, char *text, size_t n) {
    memset(s, 0, sizeof *s);
    if (n < 16) { memcpy(s->u.buf, text, n); s->u.buf[n] = 0; s->cap = 15; }
    else { s->u.ptr = text; s->cap = n; }
    s->size = n;
}
static const char *msstr_chars(const u8 *s) { return *(u64 *)(s + 0x18) >= 16 ? *(const char **)s : (const char *)s; }

#define DEBUGOUT_ADDR 0x14046d540ULL
static const u8 DEBUGOUT_EXPECT[15] = {0x40, 0x53, 0x48, 0x83, 0xEC, 0x70, 0x48, 0xC7, 0x44, 0x24, 0x20, 0xFE, 0xFF, 0xFF, 0xFF};
static const u8 PUSHLSTRING_EXPECT[8] = {0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x6C};
typedef struct { u64 addr; u8 bytes[10]; } sig_t;
static const sig_t NATIVE_SIGS[] = {
    {0x1401ab5f0ULL, {0x48, 0x89, 0x6C, 0x24, 0x20, 0x56, 0x48, 0x83, 0xEC, 0x30}}, /* zone handler */
    {0x14060a230ULL, {0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x6C, 0x24, 0x10}}, /* room type lookup */
    {0x140188a90ULL, {0x48, 0x8B, 0xC4, 0x55, 0x56, 0x57, 0x41, 0x54, 0x41, 0x55}}, /* save map */
    {0x1407fe570ULL, {0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83, 0xEC, 0x30}}, /* lua_getfield */
    {0x1407fe750ULL, {0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83, 0xEC, 0x30}}, /* lua_setfield */
    {0x1407fead0ULL, {0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83, 0xEC, 0x40}}, /* lua_pcall */
    {0x1407fdff0ULL, {0x85, 0xD2, 0x78, 0x42, 0x4C, 0x63, 0xC2, 0x48, 0x8B, 0x51}}, /* lua_settop */
    {0x1407fe3a0ULL, {0x48, 0x8B, 0x41, 0x10, 0xF2, 0x0F, 0x11, 0x08, 0xC7, 0x40}}, /* lua_pushnumber */
    {0x14045f910ULL, {0x48, 0x83, 0xEC, 0x28, 0x48, 0x8B, 0x05, 0xE5, 0x7F, 0x8F}}, /* Game.GetGameSpeed (world+0x88) */
    {0x1406ed2c0ULL, {0x85, 0xD2, 0x0F, 0x88, 0x15, 0x01, 0x00, 0x00, 0x57, 0x48}}, /* start research */
    {0x1406ecfc0ULL, {0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x6C, 0x24, 0x10}}, /* research lookup */
    {0x140665840ULL, {0x48, 0x89, 0x5C, 0x24, 0x08, 0x57, 0x48, 0x83, 0xEC, 0x50}}, /* SetIntakeType */
    {0x140699600ULL, {0x48, 0x89, 0x5C, 0x24, 0x08, 0x48, 0x89, 0x6C, 0x24, 0x10}}, /* SetCable */
    {0x1403c17d0ULL, {0x48, 0x83, 0xEC, 0x28, 0x85, 0xD2, 0x78, 0x26, 0x45, 0x85}}, /* water cell accessor */
    {0x140769730ULL, {0x48, 0x89, 0x6C, 0x24, 0x20, 0x41, 0x54, 0x41, 0x56, 0x41}}, /* water neighbour update */
    {0x1405a0410ULL, {0x48, 0x83, 0xEC, 0x68, 0x48, 0xC7, 0x44, 0x24, 0x30, 0xFE}}, /* finance ledger */
    {0x1405021f0ULL, {0x48, 0x8B, 0xC4, 0x44, 0x88, 0x40, 0x18, 0x48, 0x89, 0x48}}, /* contraband: start search */
    {0x140503ec0ULL, {0x48, 0x89, 0x4C, 0x24, 0x08, 0x53, 0x55, 0x56, 0x57, 0x41}}, /* contraband: stop search */
    {0x140502130ULL, {0x48, 0x83, 0xEC, 0x28, 0x80, 0x79, 0x63, 0x00, 0x74, 0x09}}, /* contraband: announce */
    {0x1407c7c30ULL, {0x40, 0x53, 0x48, 0x83, 0xEC, 0x20, 0x80, 0xB9, 0xDC, 0x05}}, /* toggle bangup */
    {0x1407c77e0ULL, {0x40, 0x56, 0x48, 0x83, 0xEC, 0x20, 0x48, 0x8B, 0x05, 0x13}}, /* toggle lockdown */
};

static u8 *get_world(void) { u8 *app = *APP_PTR; return app ? *(u8 **)(app + 0x198) : 0; }

static int arg_count(void *L) {
    u8 *base = *(u8 **)((u8 *)L + 0x18), *top = *(u8 **)((u8 *)L + 0x10);
    return (int)((top - base) / 16);
}
static int arg_type(void *L, int idx) {
    if (idx >= arg_count(L)) return -1;
    return *(i32 *)(*(u8 **)((u8 *)L + 0x18) + 16 * idx + 8);
}
static int arg_string(void *L, int idx, const char **s, size_t *n) {
    if (arg_type(L, idx) != 4) return 0;
    u8 *ts = *(u8 **)(*(u8 **)((u8 *)L + 0x18) + 16 * idx);
    *n = *(size_t *)(ts + 0x10);
    *s = (const char *)(ts + 0x18);
    return 1;
}
static int push_str(void *L, const char *s) { lua_pushlstring(L, s, slen(s)); return 1; }

/* ---- pump state (main thread only, apart from reads in status_line) ---- */
static void *g_L = 0;             /* world-script Lua state that said hello */
static u8 *g_world = 0;           /* world it belongs to; a change invalidates g_L */
static u32 g_main_tid = 0;
static int g_has_pump = 0, g_pumping = 0, g_pump_enabled = 1;
static u64 g_pumped = 0, g_last_pump = 0, g_frames = 0;

/* ---- zoning ---- */
static int native_zone(void *L, const char *s, size_t n) {
    char name[64]; size_t k = 0;
    const char *end = s + n;
    while (s < end && *s != ' ' && k < 63) name[k++] = *s++;
    name[k] = 0;
    i32 x1, y1, x2, y2;
    if (!k || !parse_int(&s, end, &x1) || !parse_int(&s, end, &y1) || !parse_int(&s, end, &x2) || !parse_int(&s, end, &y2))
        return push_str(L, "error: usage zone:<RoomType> x1 y1 x2 y2");
    if (!get_world()) return push_str(L, "error: no prison loaded");
    if (x2 < x1) { i32 t = x1; x1 = x2; x2 = t; }
    if (y2 < y1) { i32 t = y1; y1 = y2; y2 = t; }
    u8 cmd[0x80]; memset(cmd, 0, sizeof cmd);
    msstr *str = (msstr *)(cmd + 0x10);
    msstr_ref(str, name, k);
    i32 id = roomtype_lookup(str);
    if (id < 0) return push_str(L, "error: unknown room type");
    *(i32 *)(cmd + 0x58) = x1; *(i32 *)(cmd + 0x5c) = y1;
    *(i32 *)(cmd + 0x64) = x2; *(i32 *)(cmd + 0x68) = y2;
    zone_handler(0, cmd);
    char out[32]; sbuf b = {out, 0, sizeof out}; sb_str(&b, "ok "); sb_int(&b, id);
    return push_str(L, out);
}

static int native_roomtypes(void *L) {
    static char out[4096]; sbuf b = {out, 0, sizeof out};
    u8 *arr = *ROOMTYPES_PTR; i32 cnt = *ROOMTYPES_COUNT;
    if (!arr || cnt <= 0 || cnt > 400) return push_str(L, "");
    for (i32 i = 0; i < cnt; i++) {
        u8 *e = arr + 0x20 * i;
        u64 len = *(u64 *)(e + 0x10);
        if (len > 64) continue;
        if (i) sb_put(&b, ",", 1);
        sb_put(&b, msstr_chars(e), (size_t)len);
    }
    return push_str(L, out);
}

/* ---- research ---- */
static int native_researchlist(void *L) {
    static char out[4096]; sbuf b = {out, 0, sizeof out};
    u8 *ent = *RESEARCH_PTR, *names = *RESEARCH_NAMES; i32 cnt = *RESEARCH_COUNT;
    if (!ent || !names || cnt <= 0 || cnt > 200) return push_str(L, "");
    for (i32 i = 0; i < cnt; i++) {
        u8 *nm = names + 0x20 * i, *e = ent + 0x80 * i;
        u64 len = *(u64 *)(nm + 0x10);
        if (!len || len > 64) continue;
        if (b.n) sb_put(&b, ",", 1);
        sb_put(&b, msstr_chars(nm), (size_t)len);
        sb_put(&b, ":", 1); sb_int(&b, e[0x6c] ? 1 : 0);
        sb_put(&b, ":", 1); sb_int(&b, (i64)(*(float *)(e + 0x70) * 100.0f + 0.5f));
    }
    return push_str(L, out);
}

static int native_research(void *L, const char *s, size_t n) {
    if (!get_world()) return push_str(L, "error: no prison loaded");
    char name[64];
    if (!n || n > 63) return push_str(L, "error: research name required");
    memcpy(name, s, n); name[n] = 0;
    msstr str; msstr_ref(&str, name, n);
    i32 idx = research_lookup(&str);
    if (idx < 0 || idx >= *RESEARCH_COUNT) return push_str(L, "error: unknown research");
    u8 *e = *RESEARCH_PTR + 0x80 * idx;
    float p = *(float *)(e + 0x70);
    if (p >= 1.0f) return push_str(L, "error: already researched");
    if (e[0x6c]) return push_str(L, "error: already being researched");
    start_research(0, idx);
    return push_str(L, e[0x6c] ? "ok" : "error: the game did not start it");
}

/* ---- saving (deferred to frame_tick so it never runs inside a Lua call) ---- */
static char g_save_name[64];
static int g_save_pending = 0;
static char g_save_result[600];

static void do_save(void) {
    g_save_pending = 0;
    sbuf r = {g_save_result, 0, sizeof g_save_result};
    u8 *app = *APP_PTR;
    u64 dlen = *(u64 *)(USERDIR_STR + 0x10);
    if (!app || !get_world()) { sb_str(&r, "error: no prison loaded"); return; }
    if (!dlen || dlen > 400) { sb_str(&r, "error: game user folder not known yet"); return; }
    static char path[600]; sbuf p = {path, 0, sizeof path};
    sb_put(&p, msstr_chars(USERDIR_STR), (size_t)dlen);
    sb_str(&p, "saves/"); sb_str(&p, g_save_name); sb_str(&p, ".prison");
    msstr s; msstr_ref(&s, path, p.n);
    u8 ok = save_map(app, &s, 1, 1, 1);
    sb_str(&r, ok ? "ok " : "error: the game reported a failed save to ");
    sb_put(&r, path, p.n);
}

static int native_save(void *L, const char *s, size_t n) {
    if (!n || n > 60) return push_str(L, "error: save name must be 1..60 characters");
    for (size_t i = 0; i < n; i++) {
        char c = s[i];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-'))
            return push_str(L, "error: save name may only use letters, digits, _ and -");
    }
    memcpy(g_save_name, s, n); g_save_name[n] = 0;
    g_save_result[0] = 0;
    g_save_pending = 1;
    return push_str(L, "queued");
}

/* ---- speed ---- */
static int native_setspeed(void *L, const char *s, size_t n) {
    u8 *w = get_world();
    if (!w) return push_str(L, "error: no prison loaded");
    /* accepts 0..10 with up to 2 decimals */
    float v = 0; int frac = 0; float scale = 1;
    for (size_t i = 0; i < n; i++) {
        char c = s[i];
        if (c == '.') { if (frac) return push_str(L, "error: bad number"); frac = 1; continue; }
        if (c < '0' || c > '9') return push_str(L, "error: bad number");
        if (frac) { scale *= 0.1f; v += (c - '0') * scale; } else v = v * 10 + (c - '0');
    }
    if (!n || v > 10) return push_str(L, "error: speed must be 0..10");
    *(float *)(w + 0x88) = v;
    return push_str(L, "ok");
}

/* ---- prisoner intake (Reports > Intake) ----
 * Intake object = world+0x1778; IntakeType @+0x2c8, IntakeNumTotal @+0x2cc, IntakeNumPerDay @+0x2d0
 * (save writer 0x14066b1b0). Daily decision 0x140665020: type 0 = none, 1 = only while there are free
 * beds, 2 = until the prison holds NumTotal, 3 = NumPerDay each day, 4 = everything offered.
 * SetIntakeType 0x140665840 writes the type, flags the change and recomputes. */
#define INTAKE_OFF 0x1778
typedef void (*set_intake_type_t)(void *intake, i32 type);
static const set_intake_type_t set_intake_type = (set_intake_type_t)0x140665840ULL;

static int native_intake(void *L, const char *s, size_t n) {
    u8 *w = get_world();
    if (!w) return push_str(L, "error: no prison loaded");
    u8 *in = w + INTAKE_OFF;
    const char *end = s + n;
    i32 type, num = -1;
    if (n) {
        if (!parse_int(&s, end, &type) || type < 0 || type > 4) return push_str(L, "error: intake type must be 0..4");
        if (s < end && !parse_int(&s, end, &num)) return push_str(L, "error: bad number");
        if (num >= 0) {
            if (type == 2) *(i32 *)(in + 0x2cc) = num;
            if (type == 3) *(i32 *)(in + 0x2d0) = num;
        }
        set_intake_type(in, type);
    }
    char out[64]; sbuf b = {out, 0, sizeof out};
    sb_int(&b, *(i32 *)(in + 0x2c8)); sb_put(&b, " ", 1);
    sb_int(&b, *(i32 *)(in + 0x2cc)); sb_put(&b, " ", 1);
    sb_int(&b, *(i32 *)(in + 0x2d0));
    return push_str(L, out);
}

/* ---- float parsing / printing for the camera ---- */
static int parse_float(const char **s, const char *end, float *out) {
    const char *p = *s; int neg = 0, any = 0; float v = 0, scale = 1; int frac = 0;
    while (p < end && *p == ' ') p++;
    if (p < end && *p == '-') { neg = 1; p++; }
    while (p < end && ((*p >= '0' && *p <= '9') || (*p == '.' && !frac))) {
        if (*p == '.') { frac = 1; p++; continue; }
        if (frac) { scale *= 0.1f; v += (*p - '0') * scale; } else v = v * 10 + (*p - '0');
        p++; any = 1;
    }
    *s = p; *out = neg ? -v : v;
    return any;
}
static void sb_float(sbuf *b, float v) {  /* 3 decimals */
    if (v < 0) { sb_put(b, "-", 1); v = -v; }
    i64 whole = (i64)v; i64 milli = (i64)((v - (float)whole) * 1000.0f + 0.5f);
    if (milli >= 1000) { whole++; milli -= 1000; }
    sb_int(b, whole); sb_put(b, ".", 1);
    char d[3] = {(char)('0' + milli / 100), (char)('0' + milli / 10 % 10), (char)('0' + milli % 10)};
    sb_put(b, d, 3);
}

/* ---- regime (daily schedule) ----
 * world+0x5a0 = regime: category pointers at +0x48 (count +0x54), category 0 = base schedule
 * ("None" in the save), others follow it while "Unspecified". A category holds 24 int32 activities
 * (one per hour) at +0, CurrentActivity @+0x60 (save writer 0x140721f00, owner 0x1406ebbc0).
 * Activity names: std::string table at 0x140df8bf0 (12 entries, filled at start-up by 0x1400969c0):
 * 0 Nothing(lock-up) 1 Sleep 2 Eat 3 Shower 4 Yard 5 Work 6 WorkLockdown 7 Lockdown 8 FreeTime
 * 9 EatLockdown 10 ShowerLockdown 11 Unspecified. */
#define REGIME_OFF 0x5a0
#define ACTIVITY_NAMES ((u8 *)0x140df8bf0ULL)
#define ACTIVITY_COUNT 12

static i32 *regime_category(i32 cat) {
    u8 *w = get_world();
    if (!w) return 0;
    u8 *reg = w + REGIME_OFF;
    u8 **arr = *(u8 ***)(reg + 0x48);
    i32 n = *(i32 *)(reg + 0x54);
    if (!arr || cat < 0 || cat >= n || n > 16) return 0;
    return (i32 *)arr[cat];
}

static int native_regime(void *L, const char *s, size_t n) {
    const char *end = s + n; i32 cat = 0;
    if (n && !parse_int(&s, end, &cat)) return push_str(L, "error: regime:<category>");
    i32 *c = regime_category(cat);
    if (!c) return push_str(L, "error: no such regime category");
    static char out[1024]; sbuf b = {out, 0, sizeof out};
    for (int h = 0; h < 24; h++) {
        if (h) sb_put(&b, ",", 1);
        i32 a = c[h];
        if (a >= 0 && a < ACTIVITY_COUNT && *(u64 *)(ACTIVITY_NAMES + 0x20 * a + 0x10) < 64)
            sb_put(&b, msstr_chars(ACTIVITY_NAMES + 0x20 * a), (size_t)*(u64 *)(ACTIVITY_NAMES + 0x20 * a + 0x10));
        else sb_int(&b, a);
    }
    return push_str(L, out);
}

static int native_setregime(void *L, const char *s, size_t n) {
    const char *end = s + n; i32 cat, hour, act;
    if (!parse_int(&s, end, &cat) || !parse_int(&s, end, &hour) || !parse_int(&s, end, &act))
        return push_str(L, "error: setregime:<category> <hour 0-23> <activity 0-11>");
    if (hour < 0 || hour > 23 || act < 0 || act >= ACTIVITY_COUNT) return push_str(L, "error: hour 0-23, activity 0-11");
    i32 *c = regime_category(cat);
    if (!c) return push_str(L, "error: no such regime category");
    c[hour] = act;
    return push_str(L, "ok");
}

/* ---- camera (app+0xc8c x, +0xc90 y, +0xc94 zoom = cells per pixel, mirrored at +0xe40;
 * written the same way by the instant branch of the CamMove handler 0x1401a7370) ---- */
static int native_camera(void *L, const char *s, size_t n) {
    u8 *app = *APP_PTR;
    if (!app || !get_world()) return push_str(L, "error: no prison loaded");
    if (n) {
        const char *end = s + n; float x, y, z;
        if (!parse_float(&s, end, &x) || !parse_float(&s, end, &y)) return push_str(L, "error: camera:<x> <y> [zoom]");
        *(float *)(app + 0xc8c) = x; *(float *)(app + 0xc90) = y;
        if (parse_float(&s, end, &z) && z > 0.001f && z < 10.0f) { *(float *)(app + 0xc94) = z; *(float *)(app + 0xe40) = z; }
    }
    char out[96]; sbuf b = {out, 0, sizeof out};
    sb_float(&b, *(float *)(app + 0xc8c)); sb_put(&b, " ", 1);
    sb_float(&b, *(float *)(app + 0xc90)); sb_put(&b, " ", 1);
    sb_float(&b, *(float *)(app + 0xc94));
    return push_str(L, out);
}

/* ---- removing utilities ----
 * cable: SetCable(world+0xb38, x, y, level) 0x140699600 (level 0 = none; marks the grid dirty)
 * pipe: water manager world+0x1628, cell = 0x1403c17d0(mgr,x,y) (0x58 bytes: type @0, hot @4);
 * the install job 0x140769850 writes the cell, sets mgr+0x148 and runs 0x140769730 on the 3x3. */
typedef void (*set_cable_t)(void *elec, i32 x, i32 y, u8 level);
typedef u8 *(*water_cell_t)(void *mgr, i32 x, i32 y);
typedef void (*water_update_t)(void *mgr, i32 x, i32 y);
typedef void (*finance_add_t)(void *fin, i32 amount, void *label);
static const set_cable_t set_cable = (set_cable_t)0x140699600ULL;
static const water_cell_t water_cell = (water_cell_t)0x1403c17d0ULL;
static const water_update_t water_update = (water_update_t)0x140769730ULL;
static const finance_add_t finance_add = (finance_add_t)0x1405a0410ULL;

static int in_map(u8 *w, i32 x, i32 y) { return x >= 0 && y >= 0 && x < *(i32 *)(w + 0x60) && y < *(i32 *)(w + 0x64); }

static int native_rmutil(void *L, const char *s, size_t n, int pipe) {
    u8 *w = get_world();
    if (!w) return push_str(L, "error: no prison loaded");
    const char *end = s + n; i32 x, y;
    if (!parse_int(&s, end, &x) || !parse_int(&s, end, &y)) return push_str(L, "error: <x> <y>");
    if (!in_map(w, x, y)) return push_str(L, "error: outside the map");
    if (!pipe) { set_cable(w + 0xb38, x, y, 0); return push_str(L, "ok"); }
    u8 *mgr = w + 0x1628;
    u8 *cell = water_cell(mgr, x, y);
    if (!cell) return push_str(L, "error: no water cell");
    *(i32 *)cell = 0; cell[4] = 0;
    mgr[0x148] = 1;
    for (int dx = -1; dx <= 1; dx++) for (int dy = -1; dy <= 1; dy++)
        if (in_map(w, x + dx, y + dy)) water_update(mgr, x + dx, y + dy);
    return push_str(L, "ok");
}

/* ---- finance ledger: 0x1405a0410(world+0x7c0, amount, label) records income/expense like the
 * game's own hiring and research charges ("research_<name>") ---- */
static int native_spend(void *L, const char *s, size_t n) {
    u8 *w = get_world();
    if (!w) return push_str(L, "error: no prison loaded");
    const char *end = s + n; i32 amount;
    if (!parse_int(&s, end, &amount)) return push_str(L, "error: spend:<amount> <label>");
    while (s < end && *s == ' ') s++;
    char label[64]; size_t k = 0;
    while (s < end && k < 63) label[k++] = *s++;
    label[k] = 0;
    msstr str; msstr_ref(&str, label, k);
    finance_add(w + 0x7c0, amount, &str);
    return push_str(L, "ok");
}

/* ---- emergencies: the game's own button handler 0x1401f7b44 (switch on the button index) ----
 * contraband manager = world+0x21a0; flags @+0x60 Shakedown, +0x61 TunnelSearch, +0x62 DrugBust.
 * Shakedown: start(c,0,0); Tunnel Search: start(c,1,0); Narcotic Search: start(c,0,1); the handler
 * then calls announce(c) (ShakedownStart sound). A running search is stopped with stop(c).
 * Bangup: toggle(world) 0x1407c7c30 (regime flag world+0x5dc); Lockdown: toggle(world) 0x1407c77e0
 * (world+0x4612). The handler's 0x1407d1ea0 call is analytics ("crisis") and is skipped. */
typedef void (*search_start_t)(void *c, u8 tunnel, u8 drugs);
typedef void (*this_fn_t)(void *p);
static const search_start_t search_start = (search_start_t)0x1405021f0ULL;
static const this_fn_t search_stop = (this_fn_t)0x140503ec0ULL;
static const this_fn_t search_announce = (this_fn_t)0x140502130ULL;
static const this_fn_t toggle_bangup = (this_fn_t)0x1407c7c30ULL;
static const this_fn_t toggle_lockdown = (this_fn_t)0x1407c77e0ULL;

static int native_emergency(void *L, const char *s, size_t n) {
    u8 *w = get_world();
    if (!w) return push_str(L, "error: no prison loaded");
    u8 *c = w + 0x21a0;
    int searching = c[0x60] || c[0x61] || c[0x62];
    if (starts(s, n, "shakedown") || starts(s, n, "tunnelsearch") || starts(s, n, "drugbust")) {
        if (searching) return push_str(L, "error: a search is already running (emergency:stopsearch first)");
        search_start(c, (u8)starts(s, n, "tunnelsearch"), (u8)starts(s, n, "drugbust"));
        search_announce(c);
    } else if (starts(s, n, "stopsearch")) {
        if (!searching) return push_str(L, "error: no search is running");
        search_stop(c);
        search_announce(c);
    } else if (starts(s, n, "bangup")) {
        toggle_bangup(w);
    } else if (starts(s, n, "lockdown")) {
        toggle_lockdown(w);
    } else if (!starts(s, n, "status")) {
        return push_str(L, "error: emergency:shakedown|tunnelsearch|drugbust|stopsearch|bangup|lockdown|status");
    }
    char out[160]; sbuf b = {out, 0, sizeof out};
    sb_str(&b, "shakedown "); sb_str(&b, c[0x60] ? "1" : "0");
    sb_str(&b, " tunnelsearch "); sb_str(&b, c[0x61] ? "1" : "0");
    sb_str(&b, " drugbust "); sb_str(&b, c[0x62] ? "1" : "0");
    sb_str(&b, " bangup "); sb_str(&b, w[0x5dc] ? "1" : "0");
    sb_str(&b, " lockdown "); sb_str(&b, w[0x4612] ? "1" : "0");
    sb_str(&b, " weaponsfree "); sb_str(&b, w[0x4614] ? "1" : "0");
    return push_str(L, out);
}

/* ---- screenshots (read the last shown frame from inside the render loop) ---- */
typedef void (__stdcall *glReadBuffer_t)(u32);
typedef void (__stdcall *glReadPixels_t)(i32, i32, i32, i32, u32, u32, void *);
typedef void (__stdcall *glGetIntegerv_t)(u32, i32 *);
typedef void (__stdcall *glPixelStorei_t)(u32, i32);
typedef u32 (__stdcall *glGetError_t)(void);
static int g_shot_pending = 0;
static char g_shot_result[400];

static void do_screenshot(void) {
    g_shot_pending = 0;
    sbuf r = {g_shot_result, 0, sizeof g_shot_result};
    void *gl = LoadLibraryA("opengl32.dll");
    glReadBuffer_t rb = gl ? (glReadBuffer_t)GetProcAddress(gl, "glReadBuffer") : 0;
    glReadPixels_t rp = gl ? (glReadPixels_t)GetProcAddress(gl, "glReadPixels") : 0;
    glGetIntegerv_t gi = gl ? (glGetIntegerv_t)GetProcAddress(gl, "glGetIntegerv") : 0;
    glPixelStorei_t ps = gl ? (glPixelStorei_t)GetProcAddress(gl, "glPixelStorei") : 0;
    glGetError_t ge = gl ? (glGetError_t)GetProcAddress(gl, "glGetError") : 0;
    if (!rb || !rp || !gi || !ps || !ge) { sb_str(&r, "error: opengl32 functions not found"); return; }
    i32 vp[4] = {0, 0, 0, 0}, oldbuf = 0, oldpack = 4;
    gi(0x0BA2 /* GL_VIEWPORT */, vp);
    i32 w = vp[2], h = vp[3];
    if (w <= 0 || h <= 0 || w > 8192 || h > 8192) { sb_str(&r, "error: bad viewport"); return; }
    u32 stride = ((u32)w * 3 + 3) & ~3u;
    u32 size = stride * (u32)h;
    u8 *buf = HeapAlloc(GetProcessHeap(), 0, 54 + size);
    if (!buf) { sb_str(&r, "error: out of memory"); return; }
    gi(0x0C02 /* GL_READ_BUFFER */, &oldbuf);
    gi(0x0D05 /* GL_PACK_ALIGNMENT */, &oldpack);
    while (ge()) {}
    ps(0x0D05, 4);
    rb(0x0404 /* GL_FRONT */);
    rp(vp[0], vp[1], w, h, 0x80E0 /* GL_BGR_EXT */, 0x1401 /* GL_UNSIGNED_BYTE */, buf + 54);
    u32 err = ge();
    rb((u32)oldbuf);
    ps(0x0D05, oldpack);
    if (err) { HeapFree(GetProcessHeap(), 0, buf); sb_str(&r, "error: glReadPixels failed"); return; }
    /* BMP header: bottom-up rows, 24 bit (glReadPixels also returns bottom-up rows) */
    memset(buf, 0, 54);
    buf[0] = 'B'; buf[1] = 'M';
    *(u32 *)(buf + 2) = 54 + size; *(u32 *)(buf + 10) = 54; *(u32 *)(buf + 14) = 40;
    *(i32 *)(buf + 18) = w; *(i32 *)(buf + 22) = h; *(u16 *)(buf + 26) = 1; *(u16 *)(buf + 28) = 24;
    *(u32 *)(buf + 34) = size;
    char path[400];
    u32 n = GetEnvironmentVariableA("LOCALAPPDATA", path, 300);
    if (!n || n > 300) { HeapFree(GetProcessHeap(), 0, buf); sb_str(&r, "error: LOCALAPPDATA not set"); return; }
    const char *tail = "\\Introversion\\Prison Architect\\pa_bridge_screenshot.bmp";
    memcpy(path + n, tail, slen(tail) + 1);
    HANDLE f = CreateFileA(path, 0x40000000, 0, 0, 2, 0x80, 0);
    if (f == (HANDLE)(i64)-1) { HeapFree(GetProcessHeap(), 0, buf); sb_str(&r, "error: cannot write "); sb_str(&r, path); return; }
    u32 wr = 0;
    WriteFile(f, buf, 54 + size, &wr, 0);
    CloseHandle(f);
    HeapFree(GetProcessHeap(), 0, buf);
    sb_str(&r, wr == 54 + size ? "ok " : "error: short write ");
    sb_str(&r, path);
}

/* ---- the DebugOut replacement ---- */
static int __cdecl bridge_debugout(void *L) {
    const char *s; size_t n;
    if (!arg_string(L, 0, &s, &n)) return 0;
    if (n >= 1 && s[0] == 1) {
        s++; n--;
        if (starts(s, n, "poll")) {
            u64 now = GetTickCount64();
            g_last_poll = now;
            if (!g_pumping) {
                g_last_update_poll = now;
                g_main_tid = GetCurrentThreadId();
                if (g_has_pump) { g_L = L; g_world = get_world(); }
            }
            char *line = 0; size_t ln = 0;
            EnterCriticalSection(g_lock);
            for (size_t i = 0; i < g_inbox.len; i++) {
                if (g_inbox.buf[i] == '\n') {
                    if (i >= 1) {
                        line = HeapAlloc(GetProcessHeap(), 0, i);
                        if (line) { memcpy(line, g_inbox.buf + 1, i - 1); ln = i - 1; }
                        g_cur_slot = g_inbox.buf[0] - '0';
                    }
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
            if (g_native_ok && arg_count(L) == 2 && arg_type(L, 1) == 6) {
                lua_setfield(L, LUA_REGISTRYINDEX, PUMP_KEY); /* pops the pump function */
                g_has_pump = 1; g_L = L; g_world = get_world(); g_main_tid = GetCurrentThreadId();
                logs("pump registered\r\n");
            }
            return push_str(L, g_native_ok ? "pa_bridge " BRIDGE_VERSION " native" : "pa_bridge " BRIDGE_VERSION);
        }
        if (!g_native_ok) return push_str(L, "error: native actions unavailable (unexpected game build)");
        if (starts(s, n, "zone:")) return native_zone(L, s + 5, n - 5);
        if (starts(s, n, "roomtypes")) return native_roomtypes(L);
        if (starts(s, n, "setspeed:")) return native_setspeed(L, s + 9, n - 9);
        if (starts(s, n, "speed")) {
            u8 *w = get_world();
            if (!w) return 0;
            lua_pushnumber(L, (double)*(float *)(w + 0x88));
            return 1;
        }
        if (starts(s, n, "save:")) return native_save(L, s + 5, n - 5);
        if (starts(s, n, "saveresult")) return push_str(L, g_save_pending ? "pending" : g_save_result);
        if (starts(s, n, "setregime:")) return native_setregime(L, s + 10, n - 10);
        if (starts(s, n, "regime")) return native_regime(L, s + 6 + (n > 6 && s[6] == ':'), n - 6 - (n > 6 && s[6] == ':'));
        if (starts(s, n, "camera")) return native_camera(L, s + 6 + (n > 6 && s[6] == ':'), n - 6 - (n > 6 && s[6] == ':'));
        if (starts(s, n, "rmcable:")) return native_rmutil(L, s + 8, n - 8, 0);
        if (starts(s, n, "rmpipe:")) return native_rmutil(L, s + 7, n - 7, 1);
        if (starts(s, n, "spend:")) return native_spend(L, s + 6, n - 6);
        if (starts(s, n, "intake")) return native_intake(L, s + 6 + (n > 6 && s[6] == ':'), n - 6 - (n > 6 && s[6] == ':'));
        if (starts(s, n, "screenshotresult")) return push_str(L, g_shot_pending ? "pending" : g_shot_result);
        if (starts(s, n, "screenshot")) { g_shot_result[0] = 0; g_shot_pending = 1; return push_str(L, "queued"); }
        if (starts(s, n, "researchlist")) return native_researchlist(L);
        if (starts(s, n, "research:")) return native_research(L, s + 9, n - 9);
        if (starts(s, n, "emergency:")) return native_emergency(L, s + 10, n - 10);
        return 0;
    }
    out_log(s, n);
    return 0;
}

/* ---- frame hook: runs from the render loop on the main thread ---- */
static void frame_tick(void) {
    g_frames++;
    if (!g_main_tid || g_pumping || GetCurrentThreadId() != g_main_tid) return;
    u8 *w = get_world();
    if (w != g_world) g_L = 0; /* prison unloaded or replaced: its Lua state is gone */
    if (g_shot_pending) do_screenshot();
    if (!w) return;
    if (g_save_pending) do_save();
    if (!g_pump_enabled || !g_L) return;
    u64 now = GetTickCount64();
    if (now - g_last_update_poll < 250 || now - g_last_pump < 30) return;
    EnterCriticalSection(g_lock);
    int waiting = g_inbox.len > 0;
    LeaveCriticalSection(g_lock);
    if (!waiting) return;
    g_last_pump = now;
    void *L = g_L;
    int top = arg_count(L);
    lua_getfield(L, LUA_REGISTRYINDEX, PUMP_KEY);
    if (arg_type(L, top) == 6) {
        g_pumping = 1;
        if (lua_pcall(L, 0, 0, 0) != 0) logs("pump error\r\n");
        g_pumping = 0;
        g_pumped++;
    }
    lua_settop(L, top);
}

typedef void (*glu4d_t)(double, double, double, double);
typedef void (*glu9d_t)(double, double, double, double, double, double, double, double, double);
typedef int (*gluunproject_t)(double, double, double, const double *, const double *, const int *, double *, double *, double *);
void gluPerspective(double a, double b, double c, double d) { frame_tick(); ((glu4d_t)glu_real[32])(a, b, c, d); }
void gluOrtho2D(double a, double b, double c, double d) { frame_tick(); ((glu4d_t)glu_real[30])(a, b, c, d); }
void gluLookAt(double a, double b, double c, double d, double e, double f, double g, double h, double i) {
    frame_tick(); ((glu9d_t)glu_real[21])(a, b, c, d, e, f, g, h, i);
}
int gluUnProject(double wx, double wy, double wz, const double *m, const double *p, const int *v, double *ox, double *oy, double *oz) {
    frame_tick(); return ((gluunproject_t)glu_real[51])(wx, wy, wz, m, p, v, ox, oy, oz);
}

static int check_bytes(u64 addr, const u8 *expect, int n) {
    const u8 *p = (const u8 *)addr;
    for (int i = 0; i < n; i++) if (p[i] != expect[i]) return 0;
    return 1;
}

static int patch_debugout(void) {
    u8 *p = (u8 *)DEBUGOUT_ADDR;
    if (!check_bytes(DEBUGOUT_ADDR, DEBUGOUT_EXPECT, 15)) { logs("DebugOut bytes mismatch; not patching\r\n"); return 0; }
    if (!check_bytes((u64)lua_pushlstring, PUSHLSTRING_EXPECT, 8)) { logs("pushlstring bytes mismatch; not patching\r\n"); return 0; }
    g_native_ok = 1;
    for (unsigned i = 0; i < sizeof NATIVE_SIGS / sizeof NATIVE_SIGS[0]; i++)
        if (!check_bytes(NATIVE_SIGS[i].addr, NATIVE_SIGS[i].bytes, 10)) {
            logs("native function mismatch at "); loghex(NATIVE_SIGS[i].addr); logs("; zone/save/pump disabled\r\n");
            g_native_ok = 0;
        }
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
static void send_all(SOCKET c, const char *b, size_t n) {
    size_t off = 0;
    while (off < n) { int s = send(c, b + off, (i32)(n - off), 0); if (s <= 0) return; off += (size_t)s; }
}

static void status_line(SOCKET c) {
    char b[512]; sbuf s = {b, 0, sizeof b};
    u64 now = GetTickCount64();
    int nclients = 0;
    for (int k = 0; k < MAX_CLIENTS; k++) nclients += g_clients[k].used;
    sb_str(&s, "{\"type\":\"status\",\"bridge\":\"" BRIDGE_VERSION "\",\"patched\":");
    sb_str(&s, g_patched ? "true" : "false");
    sb_str(&s, ",\"native\":"); sb_str(&s, g_native_ok ? "true" : "false");
    sb_str(&s, ",\"lua_seen\":"); sb_int(&s, g_lua_hello);
    sb_str(&s, ",\"ms_since_poll\":"); sb_int(&s, g_last_poll ? (i64)(now - g_last_poll) : 4294967295LL);
    sb_str(&s, ",\"ms_since_update\":"); sb_int(&s, g_last_update_poll ? (i64)(now - g_last_update_poll) : 4294967295LL);
    sb_str(&s, ",\"pump\":"); sb_str(&s, !g_pump_enabled ? "\"off\"" : g_L ? "\"ready\"" : "\"waiting\"");
    sb_str(&s, ",\"pumped\":"); sb_int(&s, (i64)g_pumped);
    sb_str(&s, ",\"frames\":"); sb_int(&s, (i64)g_frames);
    sb_str(&s, ",\"clients\":"); sb_int(&s, nclients);
    sb_str(&s, "}\n");
    send_all(c, b, s.n);
}

static void drop_client(int k) {
    EnterCriticalSection(g_lock);
    closesocket(g_clients[k].s);
    g_clients[k].used = 0;
    bytes_free(&g_clients[k].out);
    purge_inbox(k);
    if (g_cur_slot == k) g_cur_slot = -1;
    LeaveCriticalSection(g_lock);
    logs("client disconnected\r\n");
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
    if (bind(ls, &sa, sizeof sa) != 0 || listen(ls, 8) != 0) { logs("bind/listen failed on 127.0.0.1:8972\r\n"); return 0; }
    logs("listening on 127.0.0.1:8972\r\n");
    char *rbuf = HeapAlloc(GetProcessHeap(), 0, 65536);
    bytes_t partial[MAX_CLIENTS]; memset(partial, 0, sizeof partial);
    for (;;) {
        fd_set rs; rs.fd_count = 0;
        rs.fd_array[rs.fd_count++] = ls;
        for (int k = 0; k < MAX_CLIENTS; k++) if (g_clients[k].used) rs.fd_array[rs.fd_count++] = g_clients[k].s;
        struct timeval tv = {0, 15000};
        int r = select(0, &rs, 0, 0, &tv);
        if (r < 0) { Sleep(50); continue; }
        for (u32 j = 0; r > 0 && j < rs.fd_count; j++) {
            SOCKET s = rs.fd_array[j];
            if (s == ls) {
                SOCKET c = accept(ls, 0, 0);
                if (c == INVALID_SOCKET) continue;
                int k = 0;
                while (k < MAX_CLIENTS && g_clients[k].used) k++;
                if (k == MAX_CLIENTS) {
                    const char *full = "{\"type\":\"error\",\"error\":\"too many clients (8)\"}\n";
                    send_all(c, full, slen(full)); closesocket(c); continue;
                }
                EnterCriticalSection(g_lock);
                g_clients[k].s = c; g_clients[k].used = 1; g_clients[k].out.len = 0;
                LeaveCriticalSection(g_lock);
                partial[k].len = 0;
                logs("client connected\r\n");
                status_line(c);
                continue;
            }
            int k = 0;
            while (k < MAX_CLIENTS && !(g_clients[k].used && g_clients[k].s == s)) k++;
            if (k == MAX_CLIENTS) continue;
            int got = recv(s, rbuf, 65536, 0);
            if (got <= 0) { drop_client(k); continue; }
            bytes_push(&partial[k], rbuf, (size_t)got);
            size_t start = 0;
            for (size_t i = 0; i < partial[k].len; i++) {
                if (partial[k].buf[i] != '\n') continue;
                size_t ln = i - start;
                const char *line = partial[k].buf + start;
                if (ln && line[ln - 1] == '\r') ln--;
                if (ln == 6 && starts(line, ln, "STATUS")) status_line(s);
                else if (ln == 8 && starts(line, ln, "PUMP OFF")) { g_pump_enabled = 0; status_line(s); }
                else if (ln == 7 && starts(line, ln, "PUMP ON")) { g_pump_enabled = 1; status_line(s); }
                else if (ln) {
                    char tag = (char)('0' + k);
                    EnterCriticalSection(g_lock);
                    bytes_push(&g_inbox, &tag, 1); bytes_push(&g_inbox, line, ln); bytes_push(&g_inbox, "\n", 1);
                    LeaveCriticalSection(g_lock);
                }
                start = i + 1;
            }
            bytes_consume(&partial[k], start);
        }
        /* flush outboxes */
        for (int k = 0; k < MAX_CLIENTS; k++) {
            if (!g_clients[k].used) continue;
            EnterCriticalSection(g_lock);
            size_t n = g_clients[k].out.len;
            char *tmp = 0;
            if (n) { tmp = HeapAlloc(GetProcessHeap(), 0, n); if (tmp) { memcpy(tmp, g_clients[k].out.buf, n); g_clients[k].out.len = 0; } }
            SOCKET c = g_clients[k].s;
            LeaveCriticalSection(g_lock);
            if (tmp) {
                size_t off = 0; int bad = 0;
                while (off < n) { int sent = send(c, tmp + off, (i32)(n - off), 0); if (sent <= 0) { bad = 1; break; } off += (size_t)sent; }
                HeapFree(GetProcessHeap(), 0, tmp);
                if (bad) drop_client(k);
            }
        }
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
