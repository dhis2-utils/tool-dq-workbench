Validation rule stages
======================

Validation rule stages can be used to summarize the number of validation
rule violations for a given duration and validation rule group.

Defining a new validation rule stage
------------------------------------

To define a new stage, press the *DQ monitor* link in the left menu, and
then click *New validation rule stage*. You will be presented with a form
to fill in the details of the validation rule stage.

The form consists of the following fields:

``Stage name``
   The name of the validation rule stage.

``Org unit level``
   This is the level where the validation rule analysis will be started.
   You may need to experiment with this setting to find the best fit for
   your data. The validation rule analysis will be performed on all org
   units at the specified level and below. If you set the level to 1, a
   single request will be made to the DHIS2 API for all org units. This
   may result in a set of results which is too large to be returned by
   the API. If you set the level to 2, the validation rule analysis will
   make a request for each org unit at level 2 (including all of its
   children). Thus, you can set the org unit level at a lower level to
   increase the number of requests made to the DHIS2 API (which in turn
   should reduce the overall number of individual validation rule
   results returned), but this will also increase the time it takes to
   run the validation rule analysis.

Note that the count of validation rules will be based on the period of the validation rule
violation itself. Thus you should carefully consider how you construct your validation
rule groups, and not mix data elements which are collected in different period types.

``Duration``
   The duration of the validation rule stage. This is used to determine
   the start and end dates of the validation rule analysis relative to
   the current date. The duration can be specified in days, weeks,
   months, or years with the format ``12 months``, ``3 weeks``,
   ``7 days``, etc.

``Aggregation level`` (optional, ``aggregation_level`` in the YAML)
   By default, violation counts are stored at the organisation unit where
   the violation occurred (often a facility or school). If set, counts are
   summed onto each organisation unit's ancestor at this level instead, for
   example the district. Must be greater than or equal to the org unit
   level. Violations found at organisation units above this level are
   skipped and reported as errors.

   Use this when storing counts at the lowest level is impractical. In
   DHIS2 2.43 and later, a data value import is rejected as a whole if any
   value's organisation unit is not assigned to the destination data
   element's data set, or is closed for the value's period. Storing counts
   at a stable, higher level means the destination data set only needs to
   be assigned to the organisation units at that level, and closed
   facilities no longer cause the import to fail. The trade-off is that
   the stored counts can no longer be broken down below that level.

``Validation rule group``
   The validation rule group to use for the validation rule analysis. All
   validation rules in the group will be used to determine the number of
   validation rule violations.

``Destination data element``
   The data element used to store the number of validation rule
   violations detected by the validation rule stage.

``Active``
   Whether the validation rule stage is active or not. If the validation
   rule stage is not active, it will be excluded when running the
   validation rule analysis with the command line script.
