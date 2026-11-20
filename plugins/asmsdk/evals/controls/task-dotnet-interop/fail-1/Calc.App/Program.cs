using System.Runtime.InteropServices;

long[] values = [1, 2, 3, 4];
Console.WriteLine(Native.calc_sum(values, values.Length));

static class Native
{
    // Negative control: "libcalc" works on Linux and macOS, and misses calc.dll on Windows.
    [DllImport("libcalc")]
    internal static extern long calc_sum(long[] values, long count);
}
