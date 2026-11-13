"""woodsites - detection of wood industry sites and logyards in DOP20 aerial imagery.

core                shared by every module: grid maths and IDs, config, readers for the reference files
module1_reference   the reference set, independent of any model: frozen image tiles (imagery)
                    and hand-drawn polygons with chip status, background list, holdout (labelling)
module2_detection   model-specific and replaceable as a whole: model inputs (dataset),
                    later training and prediction
module3_review      later: holdout evaluation, model release, candidate review
"""
