// sum.s - the right code in the wrong file: an unqualified .s is ARM64 code to the SDK, so
// no source builds the wasm RIDs and the build stops with ASM0023.

PROTO int32_t sum_i32(const int32_t* values, int32_t count)
FUNCTION sum_i32, (i32, i32) -> (i32)
    .local i32
    block
    loop
        local.get 1
        i32.eqz
        br_if 1
        local.get 2
        local.get 0
        i32.load 0
        i32.add
        local.set 2
        local.get 0
        i32.const 4
        i32.add
        local.set 0
        local.get 1
        i32.const 1
        i32.sub
        local.set 1
        br 0
    end_loop
    end_block
    local.get 2
ENDFUNCTION sum_i32
