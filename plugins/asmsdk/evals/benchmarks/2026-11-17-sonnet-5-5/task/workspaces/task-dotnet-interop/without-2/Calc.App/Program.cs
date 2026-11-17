using System.Runtime.InteropServices;

long[] values = [1, 2, 3, 4];

Console.WriteLine(Native.CalcSum(values, values.Length));

static class Native
{
    // "calc" resolves to libcalc.so on Linux.
    [DllImport("calc", EntryPoint = "calc_sum")]
    public static extern long CalcSum(long[] values, long count);
}
