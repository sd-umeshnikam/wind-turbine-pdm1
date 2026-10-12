# Turbine components and how they fail

## Gearbox
The gearbox sits in the middle of the nacelle and speeds up the slow rotation of the blades for the generator. It runs in oil, so most gearbox failures start with oil problems: leaks, low oil level, or oil pumps that cannot keep pressure. Once lubrication drops, gears and gearbox bearings wear faster and heat up. Early warning signs are oil pressure and oil or bearing temperature drifting away from normal. In Farm A's gearbox failure (event 72) two gearbox sensors dropped together about 9 to 11 days before shutdown. In Farm C (event 12) gearbox oil pressure ran higher than normal before an oil leakage fault.

## Hydraulics
The hydraulic system supplies pressure to the brakes and, on some turbines, the blade pitch. It fails through leaks, worn accumulators (the tanks that store pressure) or pumps that cannot hold pressure. Warning signs are hydraulic pressure falling slowly, or the pump switching on more often to keep up. Hydraulics is the most common named fault category in Farm A.

## Pitch System
The pitch system turns each blade to the right angle for the wind and feathers the blades in a storm. When a blade motor or drive stops responding, the turbine reports an error such as "axis not ready" and shuts down for safety. Farm C has the most pitch faults because it controls each of its three blades separately (3-axis independent pitch), which means more motors and drives that can fail. Farm A has no pitch faults.

## Generator
The generator turns rotation into electricity. Its weak points are its bearings and electrical windings. Bearing failures usually show as rising temperature. In Farm A's generator bearing failure (event 40) the bearing temperatures ran cooler before the failure, most likely because the turbine was already producing less power, so temperature alone is not always a reliable signal.

## Transformer
The transformer steps up the voltage so power can go out to the grid. It is oil-cooled, and failures usually come from overheating or pressure building inside, for example "overpressure on the main transformer" in Farm C (event 67). Oil temperature is the most useful early warning sign.

## Rotor Brake
The rotor brake holds the rotor still for maintenance or in an emergency. It works on hydraulic pressure, so low pressure means the brake cannot grip properly. In Farm C (event 18) a 24VAC power supply fault to the rotor brake was followed by an extended standstill, and both brake caliper pressure sensors ran lower than normal beforehand.

## Bearing (main / rotor bearing)
The main bearing carries the weight of the rotor and blades. It wears over time and once damaged the turbine has to stop. This is Farm B's main problem. Temperature does not show it clearly; vibration sensors do, because a damaged bearing vibrates differently well before it fails. Farm B is the only farm with vibration sensors (drive-train and tower accelerometers), which is why bearing damage can be detected there.

## Common pattern
Every component gives a drifting sensor signal days or weeks before the actual breakdown. The platform's job is to catch that drift early so the part can be repaired before it fails.
