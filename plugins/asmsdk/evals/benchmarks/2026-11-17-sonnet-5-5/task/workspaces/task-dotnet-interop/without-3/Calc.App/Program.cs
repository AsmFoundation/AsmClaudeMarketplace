using System.Runtime.InteropServices;

long[] values = [1, 2, 3, 4];

Console.WriteLine(Native.CalcSum(values, values.Length));

internal static class Native
{
    // int64_t calc_sum(const int64_t *values, int64_t count), exported by libcalc.so.
    // "calc" resolves to libcalc.so on Linux.
    [DllImport("calc", EntryPoint = "calc_sum", CallingConvention = CallingConvention.Cdecl)]
    internal static extern long CalcSum(long[] values, long count);
}
