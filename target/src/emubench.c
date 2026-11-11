/*
 * emubench - resource benchmarks for the emulator evaluation.
 *
 * Measures CPU, memory allocation, memory bandwidth and I/O performance from
 * inside the target OS. The same source is built for every target
 * architecture, and every test runs for a fixed wall-clock time, so the suite
 * takes about as long under full CPU emulation as it does natively.
 *
 * Each measurement is printed as one line:
 *   EMU-RESULT: {"area": ..., "test": ..., "value": ..., "unit": ...}
 *
 * Bump EMUBENCH_VERSION whenever a test's method changes; results are only
 * comparable between runs of the same version (evaluation/workloads.json).
 */
#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define EMUBENCH_VERSION "1.0.0"

static double opt_seconds = 2.0;    /* wall-clock time per test */
static int opt_threads = 0;         /* 0: one per online CPU */
static int opt_mem_mb = 64;         /* buffer size for the bandwidth tests */
static int opt_io_mb = 256;         /* file size for the I/O tests */
static const char *opt_dir = ".";

static double now(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static uint64_t rng_next(uint64_t *state)
{
    uint64_t x = *state;
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    return *state = x;
}

static void emit(const char *area, const char *test, double value, const char *unit, const char *extra)
{
    printf("EMU-RESULT: {\"area\": \"%s\", \"test\": \"%s\", \"value\": %.3f, \"unit\": \"%s\"%s%s}\n",
           area, test, value, unit, extra && *extra ? ", " : "", extra ? extra : "");
    fflush(stdout);
}

static void emit_skip(const char *area, const char *test, const char *reason)
{
    printf("EMU-RESULT: {\"area\": \"%s\", \"test\": \"%s\", \"value\": null, \"unit\": null, \"unavailable\": \"%s: %s\"}\n",
           area, test, reason, strerror(errno));
    fflush(stdout);
}

/* ------------------------------------------------------------- SHA-256 --- */

static const uint32_t sha_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void sha256_block(uint32_t h[8], const uint8_t *p)
{
    uint32_t w[64], a, b, c, d, e, f, g, hh;
    int i;
    for (i = 0; i < 16; i++)
        w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (; i < 64; i++) {
        uint32_t s0 = ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = h[0]; b = h[1]; c = h[2]; d = h[3]; e = h[4]; f = h[5]; g = h[6]; hh = h[7];
    for (i = 0; i < 64; i++) {
        uint32_t t1 = hh + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + sha_k[i] + w[i];
        uint32_t t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
}

/* Known-answer test: SHA-256 of one zero-filled 64-byte block (no padding). */
static int sha256_selftest(void)
{
    uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    uint8_t zero[64] = {0};
    sha256_block(h, zero);
    return h[0] == 0xda5698be && h[7] == 0x1837a9d8;
}

/* ----------------------------------------------------------------- CPU --- */

struct sha_job {
    pthread_t thread;
    double deadline;
    uint64_t bytes;
    uint32_t digest;
};

static void *sha_worker(void *arg)
{
    struct sha_job *job = arg;
    enum { BUF = 64 * 1024 };
    uint8_t *buf = malloc(BUF);
    uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    uint64_t seed = 0x1234567 + (uintptr_t)job;
    size_t i;
    for (i = 0; i < BUF; i++)
        buf[i] = (uint8_t)rng_next(&seed);
    do {
        for (i = 0; i < BUF; i += 64)
            sha256_block(h, buf + i);
        job->bytes += BUF;
    } while (now() < job->deadline);
    job->digest = h[0];
    free(buf);
    return NULL;
}

static void cpu_sha256(int threads, const char *test)
{
    struct sha_job *jobs = calloc((size_t)threads, sizeof(*jobs));
    double start = now(), elapsed;
    uint64_t total = 0;
    char extra[64];
    int i;
    for (i = 0; i < threads; i++) {
        jobs[i].deadline = start + opt_seconds;
        pthread_create(&jobs[i].thread, NULL, sha_worker, &jobs[i]);
    }
    for (i = 0; i < threads; i++) {
        pthread_join(jobs[i].thread, NULL);
        total += jobs[i].bytes;
    }
    elapsed = now() - start;
    snprintf(extra, sizeof(extra), "\"threads\": %d", threads);
    emit("cpu", test, (double)total / 1048576.0 / elapsed, "MiB/s", extra);
    free(jobs);
}

static void cpu_matmul(void)
{
    enum { N = 96 };
    static double a[N][N], b[N][N], c[N][N];
    double start, elapsed, check = 0;
    uint64_t iterations = 0;
    int i, j, k;
    for (i = 0; i < N; i++)
        for (j = 0; j < N; j++) {
            a[i][j] = (double)(i + j) / N;
            b[i][j] = (double)(i - j) / N;
        }
    start = now();
    do {
        for (i = 0; i < N; i++)
            for (j = 0; j < N; j++) {
                double sum = 0;
                for (k = 0; k < N; k++)
                    sum += a[i][k] * b[k][j];
                c[i][j] = sum;
            }
        check += c[iterations % N][(iterations * 7) % N];
        iterations++;
    } while ((elapsed = now() - start) < opt_seconds);
    /* One multiply and one add per inner step. */
    emit("cpu", "matmul_f64", 2.0 * N * N * N * (double)iterations / elapsed / 1e6, "Mflop/s",
         check != check ? "\"error\": \"NaN\"" : "\"threads\": 1");
}

/* ----------------------------------------------------- memory allocation --- */

static void mem_malloc_churn(void)
{
    enum { SLOTS = 4096 };
    static void *slot[SLOTS];
    uint64_t ops = 0, seed = 0xabcdef12345ull;
    double start = now(), elapsed;
    int i;
    do {
        for (i = 0; i < 1024; i++) {
            uint64_t r = rng_next(&seed);
            unsigned idx = (unsigned)(r % SLOTS);
            if (slot[idx]) {
                free(slot[idx]);
                slot[idx] = NULL;
            } else {
                /* Sizes spread evenly across powers of two from 16 B to 64 KiB. */
                size_t size = (size_t)16 << ((r >> 16) % 13);
                size += (size_t)((r >> 32) % size);
                char *p = malloc(size);
                if (p) {
                    p[0] = (char)r;
                    p[size - 1] = (char)r;
                }
                slot[idx] = p;
            }
            ops++;
        }
    } while ((elapsed = now() - start) < opt_seconds);
    for (i = 0; i < SLOTS; i++) {
        free(slot[i]);
        slot[i] = NULL;
    }
    emit("memory_allocation", "malloc_churn", (double)ops / elapsed / 1e6, "Mops/s", "\"sizes\": \"16B-128KiB\"");
}

static void mem_page_fault(void)
{
    const size_t size = 64u * 1024 * 1024;
    const long page = sysconf(_SC_PAGESIZE);
    uint64_t pages = 0;
    double start = now(), elapsed;
    char extra[64];
    do {
        volatile char *p = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        size_t off;
        if (p == MAP_FAILED) {
            emit_skip("memory_allocation", "page_fault", "mmap");
            return;
        }
        /* Fault in every base page, whatever the kernel's huge-page policy. */
        madvise((void *)p, size, MADV_NOHUGEPAGE);
        for (off = 0; off < size; off += (size_t)page)
            p[off] = 1;
        munmap((void *)p, size);
        pages += size / (size_t)page;
    } while ((elapsed = now() - start) < opt_seconds);
    snprintf(extra, sizeof(extra), "\"page_bytes\": %ld", page);
    emit("memory_allocation", "page_fault", (double)pages * (double)page / 1048576.0 / elapsed, "MiB/s", extra);
}

/* ------------------------------------------------------ memory bandwidth --- */

static void mem_bandwidth(void)
{
    const size_t size = (size_t)opt_mem_mb * 1024 * 1024;
    const size_t n = size / sizeof(double);
    double *a = malloc(size), *b = malloc(size), *c = malloc(size);
    double best_set = 0, best_copy = 0, best_triad = 0, start, t, mib = (double)size / 1048576.0;
    char extra[64];
    size_t i;
    int rounds = 0;
    if (!a || !b || !c) {
        emit_skip("memory_bandwidth", "memset", "malloc");
        free(a); free(b); free(c);
        return;
    }
    for (i = 0; i < n; i++) {
        a[i] = 1.0; b[i] = 2.0; c[i] = 0.5;   /* touch every page first */
    }
    start = now();
    do {
        t = now();
        memset(a, (rounds & 0x7f) + 1, size);   /* never zero: zero fills take a faster path */
        t = now() - t;
        if (mib / t > best_set) best_set = mib / t;

        t = now();
        memcpy(b, a, size);
        t = now() - t;
        if (mib / t > best_copy) best_copy = mib / t;

        for (i = 0; i < n; i++)
            b[i] = 2.0;
        t = now();
        for (i = 0; i < n; i++)
            a[i] = b[i] + 3.0 * c[i];
        t = now() - t;
        /* The triad reads two arrays and writes one. */
        if (3 * mib / t > best_triad) best_triad = 3 * mib / t;
        rounds++;
    } while (now() - start < opt_seconds * 2 || rounds < 3);
    snprintf(extra, sizeof(extra), "\"buffer_mib\": %d, \"rounds\": %d", opt_mem_mb, rounds);
    emit("memory_bandwidth", "memset", best_set, "MiB/s", extra);
    emit("memory_bandwidth", "memcpy", best_copy, "MiB/s", extra);
    emit("memory_bandwidth", "stream_triad", a[n / 2] == 3.5 ? best_triad : -1, "MiB/s", extra);
    free(a); free(b); free(c);
}

/* ----------------------------------------------------------------- I/O --- */

enum { IO_BLOCK = 1024 * 1024, IO_PAGE = 4096 };

static int open_direct(const char *path, int flags, int *direct)
{
    int fd = open(path, flags | O_DIRECT, 0644);
    *direct = fd >= 0;
    if (fd < 0)
        fd = open(path, flags, 0644);   /* filesystem without O_DIRECT */
    return fd;
}

static void io_tests(void)
{
    char path[4096], extra[96];
    const uint64_t file_size = (uint64_t)opt_io_mb * 1024 * 1024;
    const uint64_t file_pages = file_size / IO_PAGE;
    unsigned char *block;
    uint64_t seed = 0x5eed5eed5eedull, done, ops;
    double start, elapsed;
    int fd, direct;
    size_t i;

    if (posix_memalign((void **)&block, IO_PAGE, IO_BLOCK)) {
        emit_skip("io", "seq_write", "posix_memalign");
        return;
    }
    for (i = 0; i < IO_BLOCK; i++)      /* incompressible, non-zero data */
        block[i] = (unsigned char)rng_next(&seed);
    snprintf(path, sizeof(path), "%s/emubench.%ld.tmp", opt_dir, (long)getpid());

    /* Sequential write, timed through fsync. */
    fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        emit_skip("io", "seq_write", path);
        free(block);
        return;
    }
    start = now();
    for (done = 0; done < file_size; done += IO_BLOCK) {
        if (write(fd, block, IO_BLOCK) != IO_BLOCK) {
            emit_skip("io", "seq_write", "write");
            close(fd);
            unlink(path);
            free(block);
            return;
        }
    }
    fsync(fd);
    elapsed = now() - start;
    posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED);
    close(fd);
    snprintf(extra, sizeof(extra), "\"file_mib\": %d, \"block_bytes\": %d", opt_io_mb, IO_BLOCK);
    emit("io", "seq_write", (double)file_size / 1048576.0 / elapsed, "MiB/s", extra);

    /* Sequential read, bypassing the page cache where the filesystem allows. */
    fd = open_direct(path, O_RDONLY, &direct);
    start = now();
    for (done = 0; done < file_size; done += IO_BLOCK)
        if (read(fd, block, IO_BLOCK) != IO_BLOCK)
            break;
    elapsed = now() - start;
    close(fd);
    snprintf(extra, sizeof(extra), "\"file_mib\": %d, \"block_bytes\": %d, \"direct\": %s", opt_io_mb, IO_BLOCK,
             direct ? "true" : "false");
    if (done == file_size)
        emit("io", "seq_read", (double)file_size / 1048576.0 / elapsed, "MiB/s", extra);
    else
        emit_skip("io", "seq_read", "read");

    /* Random 4 KiB reads. */
    fd = open_direct(path, O_RDONLY, &direct);
    ops = 0;
    start = now();
    do {
        for (i = 0; i < 64; i++, ops++)
            if (pread(fd, block, IO_PAGE, (off_t)(rng_next(&seed) % file_pages) * IO_PAGE) != IO_PAGE)
                break;
    } while (i == 64 && (elapsed = now() - start) < opt_seconds);
    elapsed = now() - start;
    close(fd);
    snprintf(extra, sizeof(extra), "\"block_bytes\": %d, \"direct\": %s", IO_PAGE, direct ? "true" : "false");
    if (i == 64)
        emit("io", "rand_read_4k", (double)ops / elapsed, "IOPS", extra);
    else
        emit_skip("io", "rand_read_4k", "pread");

    /* Random 4 KiB writes, timed through one final fdatasync. */
    fd = open_direct(path, O_WRONLY, &direct);
    ops = 0;
    start = now();
    do {
        for (i = 0; i < 64; i++, ops++)
            if (pwrite(fd, block, IO_PAGE, (off_t)(rng_next(&seed) % file_pages) * IO_PAGE) != IO_PAGE)
                break;
    } while (i == 64 && now() - start < opt_seconds);
    fdatasync(fd);
    elapsed = now() - start;
    close(fd);
    snprintf(extra, sizeof(extra), "\"block_bytes\": %d, \"direct\": %s", IO_PAGE, direct ? "true" : "false");
    if (i == 64)
        emit("io", "rand_write_4k", (double)ops / elapsed, "IOPS", extra);
    else
        emit_skip("io", "rand_write_4k", "pwrite");

    /* Durable small writes: 4 KiB append followed by fdatasync, each time. */
    fd = open(path, O_WRONLY | O_APPEND);
    ops = 0;
    start = now();
    do {
        if (write(fd, block, IO_PAGE) != IO_PAGE || fdatasync(fd) != 0)
            break;
        ops++;
    } while ((elapsed = now() - start) < opt_seconds);
    elapsed = now() - start;
    close(fd);
    emit("io", "sync_write_4k", (double)ops / elapsed, "IOPS", "\"block_bytes\": 4096");

    unlink(path);
    free(block);
}

/* ---------------------------------------------------------------- main --- */

static int wants(const char *areas, const char *area)
{
    size_t len = strlen(area);
    const char *p = areas;
    if (!areas)
        return 1;
    while ((p = strstr(p, area)) != NULL) {
        if ((p == areas || p[-1] == ',') && (p[len] == ',' || p[len] == '\0'))
            return 1;
        p += len;
    }
    return 0;
}

static void usage(void)
{
    fputs("usage: emubench [--areas cpu,memory_allocation,memory_bandwidth,io] [--seconds S]\n"
          "                [--threads N] [--mem-mb MIB] [--io-mb MIB] [--dir DIR] [--version]\n",
          stderr);
}

int main(int argc, char **argv)
{
    const char *areas = NULL;
    int i;
    for (i = 1; i < argc; i++) {
        const char *arg = argv[i];
        const char *val = i + 1 < argc ? argv[i + 1] : NULL;
        if (!strcmp(arg, "--version")) {
            puts(EMUBENCH_VERSION);
            return 0;
        } else if (!strcmp(arg, "--areas") && val) { areas = val; i++; }
        else if (!strcmp(arg, "--seconds") && val) { opt_seconds = atof(val); i++; }
        else if (!strcmp(arg, "--threads") && val) { opt_threads = atoi(val); i++; }
        else if (!strcmp(arg, "--mem-mb") && val) { opt_mem_mb = atoi(val); i++; }
        else if (!strcmp(arg, "--io-mb") && val) { opt_io_mb = atoi(val); i++; }
        else if (!strcmp(arg, "--dir") && val) { opt_dir = val; i++; }
        else { usage(); return 64; }
    }
    if (opt_seconds <= 0 || opt_mem_mb <= 0 || opt_io_mb <= 0) {
        usage();
        return 64;
    }
    if (opt_threads <= 0) {
        /* The CPUs this process may run on, which a container can restrict. */
        cpu_set_t set;
        if (sched_getaffinity(0, sizeof(set), &set) == 0)
            opt_threads = CPU_COUNT(&set);
        else
            opt_threads = (int)sysconf(_SC_NPROCESSORS_ONLN);
    }
    if (opt_threads < 1)
        opt_threads = 1;
    if (!sha256_selftest()) {
        fputs("emubench: SHA-256 self-test failed; CPU results would be meaningless\n", stderr);
        return 70;
    }

    printf("EMU-WORKLOAD: {\"id\": \"bench\", \"version\": \"%s\", \"seconds_per_test\": %.2f, \"threads\": %d}\n",
           EMUBENCH_VERSION, opt_seconds, opt_threads);
    fflush(stdout);

    if (wants(areas, "cpu")) {
        cpu_sha256(1, "sha256_1t");
        cpu_sha256(opt_threads, "sha256_mt");
        cpu_matmul();
    }
    if (wants(areas, "memory_allocation")) {
        mem_malloc_churn();
        mem_page_fault();
    }
    if (wants(areas, "memory_bandwidth"))
        mem_bandwidth();
    if (wants(areas, "io"))
        io_tests();
    return 0;
}
