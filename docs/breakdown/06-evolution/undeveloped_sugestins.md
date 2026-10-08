Lets change the schema for the workflow 

see the example change below:

<action function="parameter_sweep">
    <parameter_name value="parameter_1"/>
    <values value="5, 10, 15"/>
</action>

to 

<action function="parameter_sweep">
    <argument key="parameter_name" value="parameter_1"/>
    <argument key="values" value="5, 10, 15"/>
</action>

for the function 

def parameter_sweep(
    parameter_name: str | None = None,
    values: str | list | tuple | None = None,
    **kwargs: object,
) -> list[Action]:

this is to make the schema clearer regarding what it actually does