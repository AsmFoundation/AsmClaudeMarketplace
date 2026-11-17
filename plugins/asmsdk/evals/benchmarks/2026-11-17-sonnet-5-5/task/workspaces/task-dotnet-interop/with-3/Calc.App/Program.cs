// Calls calc_sum from libcalc.so (built by Calc.Native) through P/Invoke.
// libcalc.so is a Linux x86-64 ELF library, so this program runs on Linux x64 only.
using System.Runtime.InteropServices;

long[] values = [1, 2, 3, 4];

Console.WriteLine(Native.CalcSum(values));

internal static partial class Native
{
    // int64_t calc_sum(const int64_t *values, int64_t count)
    // "calc" resolves to libcalc.so, which the project reference copies next to the program.
    [LibraryImport("calc", EntryPoint = "calc_sum")]
    private static unsafe partial long CalcSumNative(long* values, long count);

    internal static unsafe long CalcSum(ReadOnlySpan<long> values)
    {
        fixed (long* pValues = values)
        {
            return CalcSumNative(pValues, values.Length);
        }
    }
}
