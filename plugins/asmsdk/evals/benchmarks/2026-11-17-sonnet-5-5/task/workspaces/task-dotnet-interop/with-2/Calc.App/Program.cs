using System.Runtime.InteropServices;

long[] values = [1, 2, 3, 4];

Console.WriteLine(Native.CalcSum(values, values.Length));

internal static partial class Native
{
    // int64_t calc_sum(const int64_t *values, int64_t count), exported by libcalc.so.
    // "calc" is probed as libcalc.so on Linux, starting in the application folder.
    [LibraryImport("calc", EntryPoint = "calc_sum")]
    internal static partial long CalcSum(long[] values, long count);
}
