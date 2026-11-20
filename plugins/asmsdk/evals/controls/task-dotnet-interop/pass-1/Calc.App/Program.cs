using System.Runtime.InteropServices;

long[] values = [1, 2, 3, 4];
Console.WriteLine(Native.CalcSum(values, values.Length));

static partial class Native
{
    // "calc": .NET probes calc.dll, libcalc.so and libcalc.dylib.
    [LibraryImport("calc", EntryPoint = "calc_sum")]
    internal static partial long CalcSum(long[] values, long count);
}
