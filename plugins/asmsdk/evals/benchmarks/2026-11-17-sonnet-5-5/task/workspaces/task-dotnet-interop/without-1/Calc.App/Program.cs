using System.Runtime.InteropServices;

long[] values = [1, 2, 3, 4];

Console.WriteLine(Native.CalcSum(values, values.Length));

internal static class Native
{
    // "calc" resolves to libcalc.so (next to Calc.App.dll) on Linux.
    [DllImport("calc", EntryPoint = "calc_sum")]
    internal static extern long CalcSum(long[] values, long count);
}
