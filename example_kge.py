import pandas as pd
from sklearn.pipeline import Pipeline
from vectograph.utils import ignore_columns, num_unique_values_per_column
from vectograph.transformers import ApplyKGE, KGCreator

# settings
pd.set_option('display.max_rows', 500)
pd.set_option('display.max_columns', 500)
pd.set_option('display.width', 1000)

path_of_folder = '/home/demir/Desktop/data_files/'
tabular_csv_data_name = 'stock_change'  # (2903564, 15)
# DASK can be applied.
df = pd.read_csv(path_of_folder + tabular_csv_data_name + '.csv', index_col=0, low_memory=False)
num_unique_values_per_column(df)

df = ignore_columns(df, ['customer_id', 'customer_name', 'customer_number', 'logistic_type',
                         'assortment_uuid', 'customer_item_number', 'supplier_item_number',
                         'box_number_in_site'])
df.dropna(axis='columns', thresh=len(df) // 3, inplace=True)  # drop columns having 30% NaN values.
# TODO Unfortunately, changed_at column could not recognized as datetime due to "T" in value ,i.e, 2015-04-16 T04:14:00
temp_df = df.head(1000)
temp_df['changed_at'] = pd.to_datetime(temp_df.changed_at)

temp_df.index = 'Event_' + temp_df.index.astype(str)

updated_cols = []
for col in temp_df.columns:
    if len(temp_df[col].unique()) > 50:
        temp_df.loc[:, col + '_range'] = pd.qcut(temp_df[col], 40,
                                                 labels=[col + '_quantile_' + str(i) for i in range(40)])
        updated_cols.append(col)

temp_df = ignore_columns(temp_df, updated_cols)

kg_path = path_of_folder + tabular_csv_data_name
pipe = Pipeline([('createkg', KGCreator(path=kg_path,with_brackets=False)),
                 ('embeddings', ApplyKGE(params={'kge': 'Conve',  # Distmult,Complex,Tucker,Hyper
                                                 'embedding_dim': 10,
                                                 'batch_size': 256,
                                                 'num_epochs': 10}))])

model, kg = pipe.fit_transform(X=temp_df.select_dtypes(include='category'))


# This depends on the model as some KGE learns core tensor, complex numbers etc.
entity_emb = model.state_dict()['emb_e.weight'].numpy()
relation_emb = model.state_dict()['emb_rel.weight'].numpy()
emb = pd.DataFrame(entity_emb, index=kg.entities)
rel = pd.DataFrame(relation_emb, index=kg.relations)
emb.to_csv(model.name+'_entitiy_emb.csv')
rel.to_csv(model.name+'_relation_emb.csv')

"""

APPLY UMAP
fit = umap.UMAP()
entity_low=fit.fit_transform(entity_emb)
plt.scatter(entity_low[:, 0], entity_low[:, 1])
plt.title('Distmult Entitiy embeddings')
plt.show()

relation_emb=fit.fit_transform(relation_emb)
plt.scatter(relation_emb[:, 0], relation_emb[:, 1])
plt.title('Distmult Entitiy embeddings')
plt.show()
"""