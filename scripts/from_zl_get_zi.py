'''
prototype script, from vertical grid cell centers, get edges
assumption: 
  - z_l / rho2_l / zl represents the center
  - the first edge is always 0 for depth
  - these two assumptions hold for both native and regridded vertical grids
'''



ANSWER = [
    [    0.0,    5.0, ],
    [    5.0,   15.0, ],
    [   15.0,   25.0, ],
    [   25.0,   40.0, ],
    [   40.0,   62.5, ],
    [   62.5,   87.5, ],
    [   87.5,  112.5, ],
    [  112.5,  137.5, ],
    [  137.5,  175.0, ],
    [  175.0,  225.0, ],
    [  225.0,  275.0, ],
    [  275.0,  350.0, ],
    [  350.0,  450.0, ],
    [  450.0,  550.0, ],
    [  550.0,  650.0, ],
    [  650.0,  750.0, ],
    [  750.0,  850.0, ],
    [  850.0,  950.0, ],
    [  950.0, 1050.0, ],
    [ 1050.0, 1150.0, ],
    [ 1150.0, 1250.0, ],
    [ 1250.0, 1350.0, ],
    [ 1350.0, 1450.0, ],
    [ 1450.0, 1625.0, ],
    [ 1625.0, 1875.0, ],
    [ 1875.0, 2250.0, ],
    [ 2250.0, 2750.0, ],
    [ 2750.0, 3250.0, ],
    [ 3250.0, 3750.0, ],
    [ 3750.0, 4250.0, ],
    [ 4250.0, 4750.0, ],
    [ 4750.0, 5250.0, ],
    [ 5250.0, 5750.0, ],
    [ 5750.0, 6250.0, ],
    [ 6250.0, 6750.0  ],
]

var_z_l = [
    2.5,
    10.,
    20.,
    32.5,
    51.25,
    75.,
    100.,
    125.,
    156.25,
    200.,
    250.,
    312.5,
    400.,
    500.,
    600.,
    700.,
    800.,
    900.,
    1000.,
    1100.,
    1200.,
    1300.,
    1400.,
    1537.5,
    1750.,
    2062.5,
    2500.,
    3000.,
    3500.,
    4000.,
    4500.,
    5000.,
    5500.,
    6000.,
    6500. ]

var_z_i = [ ]

for ind in range(0, len(var_z_l)):
    z_l = var_z_l[ind]

    # Note: Fixed the single '=' to '==' for the equality check
    if ind == 0:
        width = z_l
        z_l_lo = z_l - width  # Starts at 0.0
        z_l_hi = z_l + width
    else:
        # The lower bound is the upper bound of the previous interval
        z_l_lo = z_l_hi 
        # Using the midpoint formula: midpoint = (lo + hi) / 2  =>  hi = (2 * midpoint) - lo
        z_l_hi = (2 * z_l) - z_l_lo
    
    # Store the generated edges
    var_z_i.append([z_l_lo, z_l_hi])

# Optional: Print to verify it matches the desired ANSWER
for edges in var_z_i:
    print(edges)

assert var_z_i == ANSWER, "WRONG ENTRIES IN ARRAY"
print('success')

