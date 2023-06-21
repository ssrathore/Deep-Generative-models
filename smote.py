# -*- coding: utf-8 -*-
"""SMOTE.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1Qks9ODVwp-oK28v0WlxqR2nnYQrxjWOS
"""

!pip install table_evaluator
import copy
import os
import warnings
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from pathlib import Path
from tqdm import tqdm
from scipy import stats
from typing import Tuple, Dict, Union
from scipy.spatial.distance import cdist
from sklearn.model_selection import KFold
from sklearn.tree import DecisionTreeClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.decomposition import PCA
from sklearn.metrics import f1_score, mean_squared_error, jaccard_score, accuracy_score, recall_score, roc_auc_score, roc_curve, auc
from sklearn.exceptions import ConvergenceWarning
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.linear_model import Lasso, Ridge, ElasticNet, LogisticRegression
from dython.nominal import compute_associations, numerical_encoding
from table_evaluator.viz import *
from table_evaluator.metrics import *
from table_evaluator.notebook import visualize_notebook, isnotebook, EvaluationResult
from table_evaluator.utils import dict_to_df


class TableEvaluator:

    def __init__(self, real: pd.DataFrame, fake: pd.DataFrame, cat_cols=None, unique_thresh=0, metric='pearsonr',
                 verbose=False, n_samples=None, name: str = None, seed=1337):
        self.name = name
        self.unique_thresh = unique_thresh
        self.real = real.copy()
        self.fake = fake.copy()
        self.comparison_metric = getattr(stats, metric)
        self.verbose = verbose
        self.random_seed = seed

        # Make sure columns and their order are the same.
        if len(real.columns) == len(fake.columns):
            fake = fake[real.columns.tolist()]
        assert real.columns.tolist() == fake.columns.tolist(), 'Columns in real and fake dataframe are not the same'

        if cat_cols is None:
            real = real.infer_objects()
            fake = fake.infer_objects()
            self.numerical_columns = [column for column in real._get_numeric_data().columns if
                                      len(real[column].unique()) > unique_thresh]
            self.categorical_columns = [column for column in real.columns if column not in self.numerical_columns]
        else:
            self.categorical_columns = cat_cols
            self.numerical_columns = [column for column in real.columns if column not in cat_cols]

        # Make sure the number of samples is equal in both datasets.
        if n_samples is None:
            self.n_samples = min(len(self.real), len(self.fake))
        elif len(fake) >= n_samples and len(real) >= n_samples:
            self.n_samples = n_samples
        else:
            raise Exception(f'Make sure n_samples < len(fake/real). len(real): {len(real)}, len(fake): {len(fake)}')

        self.real = self.real.sample(self.n_samples)
        self.fake = self.fake.sample(self.n_samples)
        assert len(self.real) == len(self.fake), f'len(real) != len(fake)'

        self.real.loc[:, self.categorical_columns] = self.real.loc[:, self.categorical_columns].fillna('[NAN]').astype(
            str)
        self.fake.loc[:, self.categorical_columns] = self.fake.loc[:, self.categorical_columns].fillna('[NAN]').astype(
            str)

        self.real.loc[:, self.numerical_columns] = self.real.loc[:, self.numerical_columns].fillna(
            self.real[self.numerical_columns].mean())
        self.fake.loc[:, self.numerical_columns] = self.fake.loc[:, self.numerical_columns].fillna(
            self.fake[self.numerical_columns].mean())

    def plot_mean_std(self, fname=None):
        plot_mean_std(self.real, self.fake, fname=fname)

    def plot_cumsums(self, nr_cols=4, fname=None):
        nr_charts = len(self.real.columns)
        nr_rows = max(1, nr_charts // nr_cols)
        nr_rows = nr_rows + 1 if nr_charts % nr_cols != 0 else nr_rows

        max_len = 0
        # Increase the length of plots if the labels are long
        if not self.real.select_dtypes(include=['object']).empty:
            lengths = []
            for d in self.real.select_dtypes(include=['object']):
                lengths.append(max([len(x.strip()) for x in self.real[d].unique().tolist()]))
            max_len = max(lengths)

        row_height = 6 + (max_len // 30)
        fig, ax = plt.subplots(nr_rows, nr_cols, figsize=(16, row_height * nr_rows))
        fig.suptitle('Cumulative Sums per feature', fontsize=16)
        axes = ax.flatten()
        for i, col in enumerate(self.real.columns):
            r = self.real[col]
            f = self.fake.iloc[:, self.real.columns.tolist().index(col)]
            cdf(r, f, col, 'Cumsum', ax=axes[i])
        plt.tight_layout(rect=[0, 0.02, 1, 0.98])

        if fname is not None: 
            plt.savefig(fname)

        plt.show()


    def plot_correlation_difference(self, plot_diff=True, fname=None, **kwargs):
        plot_correlation_difference(self.real, self.fake, cat_cols=self.categorical_columns, plot_diff=plot_diff, fname=fname,
                                    **kwargs)

    def correlation_distance(self, how: str = 'euclidean') -> float:
        from scipy.spatial.distance import cosine
        if how == 'euclidean':
            distance_func = euclidean_distance
        elif how == 'mae':
            distance_func = mean_absolute_error
        elif how == 'rmse':
            distance_func = rmse
        elif how == 'cosine':
            def custom_cosine(a, b):
                return cosine(a.reshape(-1), b.reshape(-1))

            distance_func = custom_cosine
        else:
            raise ValueError(f'`how` parameter must be in [euclidean, mae, rmse]')

        real_corr = compute_associations(self.real, nominal_columns=self.categorical_columns, theil_u=True)
        fake_corr = compute_associations(self.fake, nominal_columns=self.categorical_columns, theil_u=True)

        return distance_func(
            real_corr.values,
            fake_corr.values
        )

    def plot_pca(self, fname=None):
        real, fake = self.convert_numerical()

        pca_r = PCA(n_components=2)
        pca_f = PCA(n_components=2)

        real_t = pca_r.fit_transform(real)
        fake_t = pca_f.fit_transform(fake)

        fig, ax = plt.subplots(1, 2, figsize=(12, 6))
        fig.suptitle('First two components of PCA', fontsize=16)
        sns.scatterplot(ax=ax[0], x=real_t[:, 0], y=real_t[:, 1])
        sns.scatterplot(ax=ax[1], x=fake_t[:, 0], y=fake_t[:, 1])
        ax[0].set_title('Real data')
        ax[1].set_title('Fake data')

        if fname is not None: 
            plt.savefig(fname)

        plt.show()

    def get_copies(self, return_len: bool = False) -> Union[pd.DataFrame, int]:
        real_hashes = self.real.apply(lambda x: hash(tuple(x)), axis=1)
        fake_hashes = self.fake.apply(lambda x: hash(tuple(x)), axis=1)

        dup_idxs = fake_hashes.isin(real_hashes.values)
        dup_idxs = dup_idxs[dup_idxs == True].sort_index().index.tolist()

        if self.verbose:
            print(f'Nr copied columns: {len(dup_idxs)}')
        copies = self.fake.loc[dup_idxs, :]

        if return_len:
            return len(copies)
        else:
            return copies

    def get_duplicates(self, return_values: bool = False) -> Tuple[Union[pd.DataFrame, int], Union[pd.DataFrame, int]]:
        real_duplicates = self.real[self.real.duplicated(keep=False)]
        fake_duplicates = self.fake[self.fake.duplicated(keep=False)]
        if return_values:
            return real_duplicates, fake_duplicates
        else:
            return len(real_duplicates), len(fake_duplicates)


    def fit_estimators(self):

        if self.verbose:
            print(f'\nFitting real')
        for i, c in enumerate(self.r_estimators):
            if self.verbose:
                print(f'{i + 1}: {type(c).__name__}')
            c.fit(self.real_x_train, self.real_y_train)

        if self.verbose:
            print(f'\nFitting fake')
        for i, c in enumerate(self.f_estimators):
            if self.verbose:
                print(f'{i + 1}: {type(c).__name__}')
            c.fit(self.fake_x_train, self.fake_y_train)

    def score_estimators(self):
        if self.target_type == 'class':
            rows = []
            for r_classifier, f_classifier, estimator_name in zip(self.r_estimators, self.f_estimators,
                                                                  self.estimator_names):
                for dataset, target, dataset_name in zip([self.real_x_test, self.fake_x_test],
                                                         [self.real_y_test, self.fake_y_test], ['real', 'fake']):
                    predictions_classifier_real = r_classifier.predict(dataset)
                    predictions_classifier_fake = f_classifier.predict(dataset)
                    f1_r = f1_score(target, predictions_classifier_real, average='micro')
                    f1_f = f1_score(target, predictions_classifier_fake, average='micro')
                    accuracy_r = accuracy_score(target, predictions_classifier_real)
                    accuracy_f = accuracy_score(target, predictions_classifier_fake)
                    recall_r = recall_score(target, predictions_classifier_real, average='micro')
                    recall_f = recall_score(target, predictions_classifier_fake, average='micro')
                    jac_sim = jaccard_score(predictions_classifier_real, predictions_classifier_fake, average='micro')
                    # print(target, predictions_classifier_fake)
                    row = {'index': f'{estimator_name}_{dataset_name}', 'f1_real': f1_r, 'f1_fake': f1_f}
                    rows.append(row)
            results = pd.DataFrame(rows).set_index('index')

        elif self.target_type == 'regr':
            r2r = [rmse(self.real_y_test, clf.predict(self.real_x_test)) for clf in self.r_estimators]
            f2f = [rmse(self.fake_y_test, clf.predict(self.fake_x_test)) for clf in self.f_estimators]

            # Calculate test set accuracies on the other dataset
            r2f = [rmse(self.fake_y_test, clf.predict(self.fake_x_test)) for clf in self.r_estimators]
            f2r = [rmse(self.real_y_test, clf.predict(self.real_x_test)) for clf in self.f_estimators]
            index = [f'real_data_{classifier}' for classifier in self.estimator_names] + \
                    [f'fake_data_{classifier}' for classifier in self.estimator_names]
            results = pd.DataFrame({'real': r2r + f2r, 'fake': r2f + f2f}, index=index)
        else:
            raise Exception(f'self.target_type should be either \'class\' or \'regr\', but is {self.target_type}.')
        return results

    def visual_evaluation(self, save_dir=None, **kwargs):
        if save_dir is None: 
            self.plot_correlation_difference(**kwargs) 
        else: 
            save_dir = Path(save_dir)
            save_dir.mkdir(parents=True, exist_ok=True)

            # self.plot_correlation_difference(fname=save_dir/'correlation_difference.png', **kwargs)
        

    def basic_statistical_evaluation(self) -> float:
        total_metrics = pd.DataFrame()
        for ds_name in ['real', 'fake']:
            ds = getattr(self, ds_name)
            metrics = {}
            # TODO: add discrete columns as factors
            num_ds = ds[self.numerical_columns]

            for idx, value in num_ds.mean().items():
                metrics[f'mean_{idx}'] = value
            for idx, value in num_ds.median().items():
                metrics[f'median_{idx}'] = value
            for idx, value in num_ds.std().items():
                metrics[f'std_{idx}'] = value
            for idx, value in num_ds.var().items():
                metrics[f'variance_{idx}'] = value
            total_metrics[ds_name] = metrics.values()

        total_metrics.index = metrics.keys()
        self.statistical_results = total_metrics
        if self.verbose:
            print('\nBasic statistical attributes:')
            print(total_metrics.to_string())
        # print(total_metrics)
        corr, p = stats.spearmanr(total_metrics['real'], total_metrics['fake'])
        return corr

    def correlation_correlation(self) -> float:
        total_metrics = pd.DataFrame()
        for ds_name in ['real', 'fake']:
            ds = getattr(self, ds_name)
            corr_df = compute_associations(ds, nominal_columns=self.categorical_columns, theil_u=True)
            values = corr_df.values
            values = values[~np.eye(values.shape[0], dtype=bool)].reshape(values.shape[0], -1)
            total_metrics[ds_name] = values.flatten()

        self.correlation_correlations = total_metrics
        corr, p = self.comparison_metric(total_metrics['real'], total_metrics['fake'])
        if self.verbose:
            print('\nColumn correlation between datasets:')
            print(total_metrics.to_string())
        return corr

    def convert_numerical(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        real = self.real
        fake = self.fake
        for c in self.categorical_columns:
            if real[c].dtype == 'object':
                real[c] = pd.factorize(real[c], sort=True)[0]
                fake[c] = pd.factorize(fake[c], sort=True)[0]

        return real, fake

    def convert_numerical_one_hot(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        real = numerical_encoding(self.real, nominal_columns=self.categorical_columns)
        columns = sorted(real.columns.tolist())
        real = real[columns]
        fake = numerical_encoding(self.fake, nominal_columns=self.categorical_columns)
        for col in columns:
            if col not in fake.columns.tolist():
                fake[col] = 0
        fake = fake[columns]

        return real, fake

    def estimator_evaluation(self, target_col: str, target_type: str = 'class', kfold: bool = False) -> float:
        
        self.target_col = target_col
        self.target_type = target_type

        # Convert both datasets to numerical representations and split x and  y
        real, fake = self.convert_numerical()

        real_x = real.drop([target_col], axis=1)
        fake_x = fake.drop([target_col], axis=1)

        assert real_x.columns.tolist() == fake_x.columns.tolist(), f'real and fake columns are different: \n{real_x.columns}\n{fake_x.columns}'

        real_y = real[target_col]
        fake_y = fake[target_col]

        # For reproducibilty:
        np.random.seed(self.random_seed)

        if target_type == 'regr':
            self.estimators = [
                RandomForestRegressor(n_estimators=20, max_depth=5, random_state=42),
                Lasso(random_state=42),
                Ridge(alpha=1.0, random_state=42),
                ElasticNet(random_state=42),
            ]
        elif target_type == 'class':
            self.estimators = [
                LogisticRegression(multi_class='auto', solver='lbfgs', max_iter=500, random_state=42),
                RandomForestClassifier(n_estimators=10, random_state=42),
                DecisionTreeClassifier(random_state=42),
                MLPClassifier([50, 50], solver='adam', activation='relu', learning_rate='adaptive', random_state=42),
            ]
        else:
            raise ValueError(f'target_type must be \'regr\' or \'class\'')

        self.estimator_names = [type(clf).__name__ for clf in self.estimators]

        # K Fold
        kf = KFold(n_splits=5)
        res = []
        for train_index, test_index in kf.split(real_y):
            self.real_x_train = real_x.iloc[train_index]
            self.real_x_test = real_x.iloc[test_index]
            self.real_y_train = real_y.iloc[train_index]
            self.real_y_test = real_y.iloc[test_index]
            self.fake_x_train = fake_x.iloc[train_index]
            self.fake_x_test = fake_x.iloc[test_index]
            self.fake_y_train = fake_y.iloc[train_index]
            self.fake_y_test = fake_y.iloc[test_index]

            self.r_estimators = copy.deepcopy(self.estimators)
            self.f_estimators = copy.deepcopy(self.estimators)

            for estimator in self.estimators:
                assert hasattr(estimator, 'fit')
                assert hasattr(estimator, 'score')

            self.fit_estimators()
            res.append(self.score_estimators())

            # Break the loop if we don't want the kfold
            if not kfold:
                break

        self.estimators_scores = pd.concat(res).groupby(level=0).mean()
        if self.verbose:
            print('\nClassifier Results:') if self.target_type == 'class' \
                else print('\nRegressor MSE-scores and their Jaccard similarities:')
            print(self.estimators_scores.to_string())

        if self.target_type == 'regr':
            corr, p = self.comparison_metric(self.estimators_scores['real'], self.estimators_scores['fake'])
            return corr
        elif self.target_type == 'class':
            mean = mean_absolute_percentage_error(self.estimators_scores['f1_real'], self.estimators_scores['f1_fake'])
            return 1 - mean
        else:
            raise ValueError('`self.target_type` should be `regr` or `class`.')

    def row_distance(self, n_samples: int = None) -> Tuple[np.number, np.number]:
        
        if n_samples is None:
            n_samples = len(self.real)

        real, fake = self.convert_numerical_one_hot()

        columns = sorted(real.columns.tolist())
        real = real[columns]

        for col in columns:
            if col not in fake.columns.tolist():
                fake[col] = 0
        fake = fake[columns]

        for column in real.columns.tolist():
            if len(real[column].unique()) > 2:
                real[column] = (real[column] - real[column].mean()) / real[column].std()
                fake[column] = (fake[column] - fake[column].mean()) / fake[column].std()
        assert real.columns.tolist() == fake.columns.tolist()

        distances = cdist(real[:n_samples], fake[:n_samples])
        min_distances = np.min(distances, axis=1)
        min_mean = np.mean(min_distances)
        min_std = np.std(min_distances)
        return min_mean, min_std

    def column_correlations(self):

        real, fake = self.convert_numerical()

        return column_correlations(real, fake, self.categorical_columns)

    def evaluate(self, target_col: str, target_type: str = 'class', metric: str = None, verbose: bool = None,
                 n_samples_distance: int = 20000, kfold: bool = False, notebook: bool = False, return_outputs: bool = False) -> Dict:
        
        self.verbose = verbose if verbose is not None else self.verbose
        self.comparison_metric = metric if metric is not None else self.comparison_metric

        warnings.filterwarnings(action='ignore', category=ConvergenceWarning)
        pd.options.display.float_format = '{:,.4f}'.format

        basic_statistical = self.basic_statistical_evaluation()
        correlation_correlation = self.correlation_correlation()
        column_correlation = self.column_correlations()
        estimators = self.estimator_evaluation(target_col=target_col, target_type=target_type, kfold=kfold)
        nearest_neighbor = self.row_distance(n_samples=n_samples_distance)

        miscellaneous_dict = {
            'Column Correlation Distance RMSE': self.correlation_distance(how='rmse'),
            'Column Correlation distance MAE': self.correlation_distance(how='mae'),
        }

        miscellaneous = pd.DataFrame({'Result': list(miscellaneous_dict.values())},
                                     index=list(miscellaneous_dict.keys()))

        privacy_metrics_dict = {
            'nearest neighbor in real mean': nearest_neighbor[0],
            'nearest neighbor in real std': nearest_neighbor[1],
        }

        privacy_report = EvaluationResult(
            name='Privacy Results',
            content=dict_to_df(privacy_metrics_dict),
        )

        privacy_tab = [privacy_report]


        efficacy_title = 'Classifier Results' if self.target_type == 'class' \
            else '\nRegressor MSE-scores'


        ml_efficacy_tab = [
            EvaluationResult(name=efficacy_title, content=self.estimators_scores)
        ]


        js_df = js_distance_df(self.real, self.fake, self.numerical_columns)

        statistical_tab = [
            EvaluationResult(name='Jensen-Shannon distance', content=js_df,
                             appendix=f'### Mean: {js_df.js_distance.mean(): .3f}'),
            EvaluationResult(name='Kolmogorov-Smirnov statistic',
                             content=kolmogorov_smirnov_df(self.real, self.fake, self.numerical_columns)
                             )
        ]


        all_results_dict = {
            'Basic statistics': basic_statistical,
            'Correlation column correlations': correlation_correlation,
            # 'Column Correlation Distance RMSE': self.correlation_distance(how='rmse'),
            # 'Column Correlation distance MAE': self.correlation_distance(how='mae'),
            # 'Mean Correlation between fake and real columns': column_correlation,
            f'{"1 - MAPE Estimator results" if self.target_type == "class" else "Correlation RMSE"}': estimators,
        }
        all_results_dict['Similarity Score'] = np.mean(list(all_results_dict.values()))

        summary = EvaluationResult(
            name='Overview Results',
            content=dict_to_df(all_results_dict)
        )

        overview_tab = [summary, ]

        if return_outputs:
            all_results = [
                *overview_tab,
                *ml_efficacy_tab,
                *privacy_tab,
                *statistical_tab,
            ]

            all_results = {x.name: x.content.to_dict(orient='index') for x in all_results}

            return all_results

        if notebook:
            visualize_notebook(
                self,
                overview=overview_tab,
                privacy_metrics=privacy_tab,
                ml_efficacy=ml_efficacy_tab,
                statistical=statistical_tab,
            )

        else:
            print(f'\n{efficacy_title}:')
            print(self.estimators_scores.to_string())

            print(f'\nAuthentication Measures:')
            print(privacy_report.content.to_string())

            # print(f'\nMiscellaneous results:')
            # print(miscellaneous.to_string())

            print(f'\nDiversity Measures:')
            print(summary.content.to_string())

import pandas as pd

df = pd.read_csv('JDT_Core.csv')
columns_to_drop = []
df1=df
df.drop(columns_to_drop, axis=1, inplace=True)
df1 = df1.sample(frac=1).reset_index(drop=True)
print(df1.info())
print(df1.head())

from sklearn.preprocessing import MinMaxScaler, OneHotEncoder, LabelEncoder
numerical_data = df.select_dtypes("number")
categorical_data = df.select_dtypes("object")
numerical_data

data_cols = list(df.columns[ df.columns != 'defects' ])
X = df[data_cols]
y = df['defects'].astype(bool)
y

from imblearn.over_sampling import SMOTE
from sklearn.model_selection import train_test_split

# split data into training and testing sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.6, random_state=5)

# create artificial data with SMOTE
oversample = SMOTE(k_neighbors=2,random_state=2)
X_train_smote, y_train_smote = oversample.fit_resample(X_train, y_train)

X_train_smote

result = pd.concat([X_train_smote, y_train_smote], axis=1, join='inner')
result

data = df1
data_fake = result
data['defects'] = data['defects'].astype(int)
table_evaluator = TableEvaluator(data, data_fake)
table_evaluator.evaluate(target_col='defects')
table_evaluator.visual_evaluation()

