// sum.wasm.s - a native habit: a named constant for the element size. llvm-mc's WebAssembly
// writer stops on any constant symbol ("absolute addressing not supported!"), so the build
// stops with ASM0019.
.set ELEMENT_SIZE, 4

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
        i32.const ELEMENT_SIZE
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
