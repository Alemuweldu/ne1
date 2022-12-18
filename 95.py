# -*- coding: utf-8 -*-
"""95.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1B9HYr_CZNdK8Qch0tvp4d_2M628-9x6V

### <a>***Import the necessary libraries***
"""

# !pip install seqeval accelerate datasets transformers sentencepiece

import numpy as np
import pandas as pd

from tqdm.auto import tqdm

import sklearn

from datasets import load_dataset, load_metric, ClassLabel, Dataset, DatasetDict

from transformers import Trainer
from transformers import AutoTokenizer
from transformers import get_scheduler
from transformers import TrainingArguments
from transformers import DataCollatorForTokenClassification
from transformers import AutoModelForTokenClassification

import torch
from torch.optim import AdamW
from torch.utils.data import DataLoader

from accelerate import Accelerator

"""### <a>***Download, Load and Read the DataSets***"""

# Commented out IPython magic to ensure Python compatibility.
import matplotlib.pyplot as plt
# %matplotlib inline
plt.style.use("ggplot")

df = pd.read_csv('NER.txt', sep=" ", header='infer', on_bad_lines='skip')
print('Shape of data: ', df.shape)
print(df.columns)
df.head()

total_sentences = []
total_targets = []

x, y = [], []
for idx, row in df.iterrows():
  if row['Text'] in ['!','?','።', '::', '፡፡', '፥']:
    total_sentences.append(x)
    total_targets.append(y)
    x, y = [], []
  else:
    x.append(row['Text'])
    y.append(row['Label'])

total_df = pd.DataFrame(list(zip(total_sentences, total_targets)), columns = ['Sentences', 'Labels'])

total_df

from sklearn.model_selection import train_test_split


X = total_df["Sentences"]
y = total_df["Labels"]


X_train, X_dev_test, y_train, y_dev_test = train_test_split(X, y, test_size=0.2)
X_dev, X_test, y_dev, y_test = train_test_split(X_dev_test, y_dev_test, test_size=0.5)

train_sentences= X_train.to_list()
train_targets  = y_train.to_list()

dev_sentences= X_dev.to_list()
dev_targets  = y_dev.to_list()

test_sentences= X_test.to_list()
test_targets  = y_test.to_list()

train_df = pd.DataFrame(list(zip(train_sentences, train_targets)), columns = ['Sentences', 'Label'])

train_dataset = Dataset.from_pandas(pd.DataFrame({'text': train_sentences, 'label': train_targets}))

text_lens = list(map(lambda x: len(x), train_dataset['text']))

np.median(text_lens), np.mean(text_lens), np.quantile(text_lens, 0.99)

plt.plot(text_lens)

dev_dataset = Dataset.from_pandas(pd.DataFrame({'text': dev_sentences, 'label': dev_targets}))

text_lens = list(map(lambda x: len(x), dev_dataset['text']))

np.median(text_lens), np.mean(text_lens), np.quantile(text_lens, 0.99)

plt.plot(text_lens)

test_dataset = Dataset.from_pandas(pd.DataFrame({'text': test_sentences, 'label': test_targets}))

dataset_dict = {
    'train': train_dataset,
    'dev': dev_dataset,
    'test': test_dataset
}

dataset = DatasetDict(dataset_dict)
print(dataset)

"""### <a>***Preprocess, Tokenize and Alignment the Data***"""

print("dataset text: ", dataset["train"][0]["text"])

ner_feature = ClassLabel(num_classes=len(df['Label'].unique()), names=df['Label'].unique())
print("ner_feature: ", ner_feature)

label_names = ner_feature.names
print("label_names: ", label_names)

words = dataset["train"][0]["text"]
labels = dataset["train"][0]["label"]

line1 = ""
line2 = ""
for word, label in zip(words, labels):
  full_label = label
  max_length = max(len(word), len(full_label))
  line1 += word + " " * (max_length - len(word) + 1)
  line2 += full_label + " " * (max_length - len(full_label) + 1)

print("line1: ", line1)
print("line2: ", line2)

model_checkpoint = "mehari/tigroberta-base"

tokenizer = AutoTokenizer.from_pretrained(model_checkpoint, add_prefix_space=True)

print("tokenizer.is_fast: ", tokenizer.is_fast)

inputs = tokenizer(dataset["train"][0]["text"], is_split_into_words=True)
print("inputs.tokens: ", inputs.tokens())

print("inputs.word_ids: ", inputs.word_ids())

def align_labels_with_tokens(labels, word_ids):
    new_labels = []
    current_word = None
    for word_id in word_ids:
        if word_id != current_word:
            # Start of a new word!
            current_word = word_id
            label = -100 if word_id is None else ner_feature.str2int(labels[word_id])
            new_labels.append(label)
        elif word_id is None:
            # Special token
            new_labels.append(-100)
        else:
            # Same word as previous token
            label = ner_feature.str2int(labels[word_id])
            # If the label is B-XXX we change it to I-XXX
            if label % 2 == 1:
                label += 1
            new_labels.append(label)

    return new_labels

labels = dataset["train"][0]["label"]
word_ids = inputs.word_ids()
print("labels: ", labels)
print("Aligned labels: ", align_labels_with_tokens(labels, word_ids))

def tokenize_and_align_labels(examples):
    tokenized_inputs = tokenizer(
        examples["text"], truncation=True, is_split_into_words=True, max_length=40
    )
    all_labels = examples["label"]
    new_labels = []
    for i, labels in enumerate(all_labels):
        word_ids = tokenized_inputs.word_ids(i)
        new_labels.append(align_labels_with_tokens(labels, word_ids))

    tokenized_inputs["labels"] = new_labels
    return tokenized_inputs

tokenized_datasets = dataset.map(
    tokenize_and_align_labels,
    batched=True,
    remove_columns=dataset["train"].column_names,
)

data_collator = DataCollatorForTokenClassification(tokenizer=tokenizer)

batch = data_collator([tokenized_datasets["train"][i] for i in range(2)])
print("Collated batch labels: ", batch["labels"])

for i in range(2):
    print(tokenized_datasets["train"][i]["labels"])

metric = load_metric("seqeval")

labels = dataset["train"][60]["label"]
print("labels: ", labels)

predictions = labels.copy()
predictions[2] = "O"
print(metric.compute(predictions=[predictions], references=[labels]))

def compute_metrics(eval_preds):
    logits, labels = eval_preds
    predictions = np.argmax(logits, axis=-1)

    # Remove ignored index (special tokens) and convert to labels
    true_labels = [[label_names[l] for l in label if l != -100] for label in labels]
    true_predictions = [
        [label_names[p] for (p, l) in zip(prediction, label) if l != -100]
        for prediction, label in zip(predictions, labels)
    ]
    all_metrics = metric.compute(predictions=true_predictions, references=true_labels)
    return {
        "precision": all_metrics["overall_precision"],
        "recall": all_metrics["overall_recall"],
        "f1": all_metrics["overall_f1"],
        "accuracy": all_metrics["overall_accuracy"],
    }

id2label = {str(i): label for i, label in enumerate(label_names)}
label2id = {v: k for k, v in id2label.items()}

label2id

id2label

"""### <a>***Training and Evaluation `(Single Model)`***

#### <a>**Preprocess and Create DataLoader (Pytorch)**
"""

train_dataloader = DataLoader(
    tokenized_datasets["train"],
    shuffle=True,
    collate_fn=data_collator,
    batch_size=8,
)
eval_dataloader = DataLoader(
    tokenized_datasets["dev"], collate_fn=data_collator, batch_size=8
)
test_dataloader = DataLoader(
    tokenized_datasets["test"], collate_fn=data_collator, batch_size=4
)

def postprocess(predictions, labels):
    predictions = predictions.detach().cpu().clone().numpy()
    labels = labels.detach().cpu().clone().numpy()

    # Remove ignored index (special tokens) and convert to labels
    true_labels = [[label_names[l] for l in label if l != -100] for label in labels]
    true_predictions = [
        [label_names[p] for (p, l) in zip(prediction, label) if l != -100]
        for prediction, label in zip(predictions, labels)
    ]
    return true_labels, true_predictions

model = AutoModelForTokenClassification.from_pretrained(
    model_checkpoint,
    id2label=id2label,
    label2id=label2id,
)

"""#### <a>**Training and Evaluation**"""

optimizer = AdamW(model.parameters(), lr=0.000005)

accelerator = Accelerator()

model, optimizer, train_dataloader, eval_dataloader, test_dataloader = accelerator.prepare(
    model, optimizer, train_dataloader, eval_dataloader, test_dataloader
)

num_train_epochs = 20
num_update_steps_per_epoch = len(train_dataloader)
num_training_steps = num_train_epochs * num_update_steps_per_epoch

lr_scheduler = get_scheduler(
    "linear",
    optimizer=optimizer,
    num_warmup_steps=0,
    num_training_steps=num_training_steps,
)

train_losses, result_list = [], []
progress_bar = tqdm(range(num_training_steps))

history_dict={"train_loss":    [],"val_loss":     [],
              "DATE_f1_score": [],"LOC_f1_score": [],"ORG_f1_score": [],"PER_f1_score": [],"MISC_f1_score":  [], "Model_f1_score":  [], 
              "DATE_precision":[],"LOC_precision":[],"ORG_precision":[],"PER_precision":[],"MISC_precision": [], "Model_precision": [],
              "DATE_recall":   [],"LOC_recall":   [],"ORG_recall":   [],"PER_recall":   [],"MISC_recall":    [], "Model_recall":    []}

for epoch in range(num_train_epochs):
    # Training
    training_loss = 0.0
    val_loss = 0.0
    model.train()
    for batch in train_dataloader:
        outputs = model(**batch)
        loss = outputs.loss
        training_loss += loss
        train_losses.append(loss)
        accelerator.backward(loss)

        optimizer.step()
        lr_scheduler.step()
        optimizer.zero_grad()
        progress_bar.update(1)

    # Evaluation
    model.eval()
    loss = 0
    for batch in eval_dataloader:
        with torch.no_grad():
            outputs = model(**batch)
            loss += outputs.loss
            val_loss += outputs.loss
        predictions = outputs.logits.argmax(dim=-1)
        labels = batch["labels"]

        # Necessary to pad predictions and labels for being gathered
        predictions = accelerator.pad_across_processes(predictions, dim=1, pad_index=-100)
        labels = accelerator.pad_across_processes(labels, dim=1, pad_index=-100)

        predictions_gathered = accelerator.gather(predictions)
        labels_gathered = accelerator.gather(labels)

        true_predictions, true_labels = postprocess(predictions_gathered, labels_gathered)
        metric.add_batch(predictions=true_predictions, references=true_labels)

    
    
    history_dict["train_loss"].append(training_loss.item())
    history_dict["val_loss"].append(val_loss.item())
        
    results = metric.compute()

    history_dict["DATE_f1_score"].append(results["DATE"]["f1"].item())
    history_dict["LOC_f1_score"].append(results["LOC"]["f1"].item())
    history_dict["MISC_f1_score"].append(results["MISC"]["f1"].item())
    history_dict["ORG_f1_score"].append(results["ORG"]["f1"].item())
    history_dict["PER_f1_score"].append(results["PER"]["f1"].item())
    history_dict["Model_f1_score"].append(results["overall_f1"].item())

    history_dict["DATE_precision"].append(results["DATE"]["precision"].item())
    history_dict["LOC_precision"].append(results["LOC"]["precision"].item())
    history_dict["MISC_precision"].append(results["MISC"]["precision"].item())
    history_dict["ORG_precision"].append(results["ORG"]["precision"].item())
    history_dict["PER_precision"].append(results["PER"]["precision"].item())
    history_dict["Model_precision"].append(results["overall_precision"].item())

    history_dict["DATE_recall"].append(results["DATE"]["recall"].item())
    history_dict["LOC_recall"].append(results["LOC"]["recall"].item())
    history_dict["MISC_recall"].append(results["MISC"]["recall"].item())
    history_dict["ORG_recall"].append(results["ORG"]["recall"].item())
    history_dict["PER_recall"].append(results["PER"]["recall"].item())
    history_dict["Model_recall"].append(results["overall_recall"].item())

    result_list.append(results)
    
    print(
        f"epoch {epoch+1}:",
        {
            key: results[f"overall_{key}"]
            for key in ["precision", "recall", "f1", "accuracy"]
        },
    )

"""#### <a>***History Plots***"""

from IPython.display import Image, display
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import seaborn as sns

plt.figure(figsize=(8,5))
plt.style.use("ggplot")
title = "Training and Validation Loss "
plt.suptitle(title, fontsize=18)

plt.plot(history_dict['train_loss'], label='Training Loss')
plt.plot(history_dict['val_loss'], label='Validation Loss')
plt.legend()
plt.xlabel('# of Epochs', fontsize=16)
plt.ylabel('Loss', fontsize=16)

plt.show()

plt.figure(figsize=(8,5))
plt.style.use("ggplot")
title = "NER F1 Scores"
plt.suptitle(title, fontsize=18)

plt.plot(history_dict['DATE_f1_score'], label='DATE f1_score')
plt.plot(history_dict['LOC_f1_score'],  label='LOC f1_score')
plt.plot(history_dict['ORG_f1_score'],  label='ORG f1_score')
plt.plot(history_dict['PER_f1_score'],  label='PER f1_score')
plt.plot(history_dict['MISC_f1_score'], label='MISC f1_score')
plt.plot(history_dict['Model_f1_score'],label='Model f1_score')
plt.legend()
plt.xlabel('# of Epochs', fontsize=16)
plt.ylabel('F1 Score', fontsize=16)

plt.show()

plt.figure(figsize=(8,5))
plt.style.use("ggplot")
title = "NER Precision"
plt.suptitle(title, fontsize=18)

plt.plot(history_dict['DATE_precision'], label='DATE Precision')
plt.plot(history_dict['LOC_precision'],  label='LOC Precision')
plt.plot(history_dict['ORG_precision'],  label='ORG Precision')
plt.plot(history_dict['PER_precision'],  label='PER Precision')
plt.plot(history_dict['MISC_precision'], label='MISC Precision')
plt.plot(history_dict['Model_precision'],label='Model Precision')
plt.legend()
plt.xlabel('# of Epochs', fontsize=16)
plt.ylabel('Precision', fontsize=16)

plt.show()

plt.figure(figsize=(8,5))
plt.style.use("ggplot")
title = "NER Recall"
plt.suptitle(title, fontsize=18)

plt.plot(history_dict['DATE_recall'], label='DATE Recall')
plt.plot(history_dict['LOC_recall'],  label='LOC Recall')
plt.plot(history_dict['ORG_recall'],  label='ORG Recall')
plt.plot(history_dict['PER_recall'],  label='PER Recall')
plt.plot(history_dict['MISC_recall'], label='MISC Recall')
plt.plot(history_dict['Model_recall'],label='Model Recall')
plt.legend()
plt.xlabel('# of Epochs', fontsize=16)
plt.ylabel('Recall', fontsize=16)

plt.show()

"""#### <a>***Evaluate the Model on the Test Data***"""

test_instance = next(iter(test_dataloader))
while True:
  instance = next(iter(test_dataloader))
  unique_labels = set(instance['labels'].tolist()[0])
  if len(unique_labels) > 2:
    test_instance = instance
    break

outputs = model(**test_instance)

predictions = outputs.logits.argmax(dim=-1)
labels = test_instance["labels"]

# Necessary to pad predictions and labels for being gathered
predictions = accelerator.pad_across_processes(predictions, dim=1, pad_index=-100)
labels = accelerator.pad_across_processes(labels, dim=1, pad_index=-100)

predictions_gathered = accelerator.gather(predictions)
labels_gathered = accelerator.gather(labels)

true_predictions, true_labels = postprocess(predictions_gathered, labels_gathered)

# Prediction

y_true = []
y_pred = []

model.eval()
for batch in test_dataloader:

  with torch.no_grad():
    outputs = model(**batch)

  predictions = outputs.logits.argmax(dim=-1)
  labels = batch["labels"]

  # Necessary to pad predictions and labels for being gathered
  predictions = accelerator.pad_across_processes(predictions, dim=1, pad_index=-100)
  labels = accelerator.pad_across_processes(labels, dim=1, pad_index=-100)

  predictions_gathered = accelerator.gather(predictions)
  labels_gathered = accelerator.gather(labels)


  true_labels, true_predictions = postprocess(predictions_gathered, labels_gathered)

  y_true +=  [tag for entry in true_labels for tag in entry]
  y_pred +=  [tag for entry in true_predictions for tag in entry]

def replace_all(text, dic):
    for i, j in dic.items():
        text = text.replace(i, j)
    return text

d = {'B-DATE':"DATE", 'B-LOC':"LOC", 'B-ORG':"ORG", 'I-ORG':"ORG", 'I-PER':"PER", 
     'B-MISC':"MISC", 'B-PER':"PER", 'I-LOC':"LOC", 'I-DATE':"DATE", 'I-MISC':"MISC"}

y_true_N= [replace_all(s, d) for s in y_true]
y_pred_N= [replace_all(s, d) for s in y_pred]

"""#### <a>***Confusion Matrix***"""

from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay

cm = confusion_matrix(y_true_N, y_pred_N, labels=list(set(y_true_N)))

fig, ax = plt.subplots(figsize=(8, 5))
disp = ConfusionMatrixDisplay.from_predictions(y_true_N, y_pred_N, ax=ax, cmap='Blues')
plt.show()

cm

from seqeval import metrics

print(metrics.classification_report([y_true], [y_pred]))

"""#### <a>**Save Model**"""

model.save_pretrained('models/fintuned/')

"""### <a>***Training and Evaluation `(Cross Validation Model)`***

#### <a>**Preprocess and Create DataLoader (Pytorch)**
"""

def align_labels_with_tokens(labels, word_ids):
    new_labels = []
    current_word = None
    for word_id in word_ids:
        if word_id != current_word:
            # Start of a new word!
            current_word = word_id
            label = -100 if word_id is None else ner_feature.str2int(labels[word_id])
            new_labels.append(label)
        elif word_id is None:
            # Special token
            new_labels.append(-100)
        else:
            # Same word as previous token
            label = ner_feature.str2int(labels[word_id])
            # If the label is B-XXX we change it to I-XXX
            if label % 2 == 1:
                label += 1
            new_labels.append(label)

    return new_labels

def tokenize_and_align_labels(examples):
    tokenized_inputs = tokenizer(
        examples["text"], truncation=True, is_split_into_words=True, max_length=40
    )
    all_labels = examples["label"]
    new_labels = []
    for i, labels in enumerate(all_labels):
        word_ids = tokenized_inputs.word_ids(i)
        new_labels.append(align_labels_with_tokens(labels, word_ids))

    tokenized_inputs["labels"] = new_labels
    return tokenized_inputs

metric = load_metric("seqeval")

def compute_metrics(eval_preds):
    logits, labels = eval_preds
    predictions = np.argmax(logits, axis=-1)

    # Remove ignored index (special tokens) and convert to labels
    true_labels = [[label_names[l] for l in label if l != -100] for label in labels]
    true_predictions = [
        [label_names[p] for (p, l) in zip(prediction, label) if l != -100]
        for prediction, label in zip(predictions, labels)
    ]
    all_metrics = metric.compute(predictions=true_predictions, references=true_labels)
    return {
        "precision": all_metrics["overall_precision"],
        "recall": all_metrics["overall_recall"],
        "f1": all_metrics["overall_f1"],
        "accuracy": all_metrics["overall_accuracy"],
    }

id2label = {str(i): label for i, label in enumerate(label_names)}
label2id = {v: k for k, v in id2label.items()}


def postprocess(predictions, labels):
    predictions = predictions.detach().cpu().clone().numpy()
    labels = labels.detach().cpu().clone().numpy()

    # Remove ignored index (special tokens) and convert to labels
    true_labels = [[label_names[l] for l in label if l != -100] for label in labels]
    true_predictions = [
        [label_names[p] for (p, l) in zip(prediction, label) if l != -100]
        for prediction, label in zip(predictions, labels)
    ]
    return true_labels, true_predictions

import numpy as np
import pandas as pd

from tqdm.auto import tqdm

import sklearn

from datasets import load_dataset, load_metric, ClassLabel, Dataset, DatasetDict

from transformers import Trainer
from transformers import AutoTokenizer
from transformers import get_scheduler
from transformers import TrainingArguments
from transformers import DataCollatorForTokenClassification
from transformers import AutoModelForTokenClassification

import torch
from torch.optim import AdamW
from torch.utils.data import DataLoader

from accelerate import Accelerator

"""#### <a>**Training and Evaluation**"""

from sklearn.model_selection import KFold

# prepare cross validation
train_df = pd.DataFrame(list(zip(train_sentences, train_targets)), columns = ['Sentences', 'Label'])
dev_df   = pd.DataFrame(list(zip(dev_sentences, dev_targets)),     columns = ['Sentences', 'Label'])
total_train_dev_df = train_df.append(dev_df, ignore_index=True)

n=10

splits = KFold(n_splits=n, random_state=42, shuffle=True)

# Start training loop
print("Start training...\n")
history_dict_folds=[]
for fold, (train_idx,val_idx) in enumerate(splits.split(np.arange(len(total_train_dev_df)))):
  
  print('Fold {}'.format(fold + 1))
  print()

  trainidx = train_idx.tolist()
  validx   = val_idx.tolist()
  tr=total_train_dev_df.iloc[trainidx]
  vl=total_train_dev_df.iloc[validx]

  train_sentences = tr["Sentences"].tolist()
  train_targets = tr["Label"].tolist()

  dev_sentences = vl["Sentences"].tolist()
  dev_targets = vl["Label"].tolist()

  train_dataset = Dataset.from_pandas(pd.DataFrame({'text': train_sentences, 'label': train_targets}))
  dev_dataset = Dataset.from_pandas(pd.DataFrame({'text': dev_sentences, 'label': dev_targets}))
  dataset_dict = {
      'train': train_dataset,
      'dev': dev_dataset}
  dataset = DatasetDict(dataset_dict)

  #Tokenization and Alignment
  ner_feature = ClassLabel(num_classes=len(df['Label'].unique()), names=df['Label'].unique())

  label_names = ner_feature.names

  model_checkpoint = "mehari/tigroberta-base"

  tokenizer = AutoTokenizer.from_pretrained(model_checkpoint, add_prefix_space=True)


  tokenized_datasets = dataset.map(tokenize_and_align_labels,batched=True,remove_columns=dataset["train"].column_names,)

  data_collator = DataCollatorForTokenClassification(tokenizer=tokenizer)

  train_dataloader = DataLoader(
      tokenized_datasets["train"],
      shuffle=True,
      collate_fn=data_collator,
      batch_size=8,
  )
  eval_dataloader = DataLoader(
      tokenized_datasets["dev"], collate_fn=data_collator, batch_size=8
  )

  model = AutoModelForTokenClassification.from_pretrained(
      model_checkpoint,
      id2label=id2label,
      label2id=label2id,
  )

  optimizer = AdamW(model.parameters(), lr=0.000005)
  accelerator = Accelerator()

  model, optimizer, train_dataloader, eval_dataloader, test_dataloader = accelerator.prepare(
      model, optimizer, train_dataloader, eval_dataloader, test_dataloader
  )

  num_train_epochs = 10
  num_update_steps_per_epoch = len(train_dataloader)
  num_training_steps = num_train_epochs * num_update_steps_per_epoch

  lr_scheduler = get_scheduler(
      "linear",
      optimizer=optimizer,
      num_warmup_steps=0,
      num_training_steps=num_training_steps,
  )

  train_losses, result_list = [], []
  progress_bar = tqdm(range(num_training_steps))

  history_dict={"train_loss":    [],"val_loss":     [],
                "DATE_f1_score": [],"LOC_f1_score": [],"ORG_f1_score": [],"PER_f1_score": [],"MISC_f1_score":  [], "Model_f1_score":  [], 
                "DATE_precision":[],"LOC_precision":[],"ORG_precision":[],"PER_precision":[],"MISC_precision": [], "Model_precision": [],
                "DATE_recall":   [],"LOC_recall":   [],"ORG_recall":   [],"PER_recall":   [],"MISC_recall":    [], "Model_recall":    []}

  for epoch in range(num_train_epochs):
      # Training
      training_loss = 0.0
      val_loss = 0.0
      model.train()
      for batch in train_dataloader:
          outputs = model(**batch)
          loss = outputs.loss
          training_loss += loss
          train_losses.append(loss)
          accelerator.backward(loss)

          optimizer.step()
          lr_scheduler.step()
          optimizer.zero_grad()
          progress_bar.update(1)

      # Evaluation
      model.eval()
      loss = 0
      for batch in eval_dataloader:
          with torch.no_grad():
              outputs = model(**batch)
              loss += outputs.loss
              val_loss += outputs.loss
          predictions = outputs.logits.argmax(dim=-1)
          labels = batch["labels"]

          # Necessary to pad predictions and labels for being gathered
          predictions = accelerator.pad_across_processes(predictions, dim=1, pad_index=-100)
          labels = accelerator.pad_across_processes(labels, dim=1, pad_index=-100)

          predictions_gathered = accelerator.gather(predictions)
          labels_gathered = accelerator.gather(labels)

          true_predictions, true_labels = postprocess(predictions_gathered, labels_gathered)
          metric.add_batch(predictions=true_predictions, references=true_labels)

      
      
      history_dict["train_loss"].append(training_loss.item())
      history_dict["val_loss"].append(val_loss.item())
          
      results = metric.compute()

      history_dict["DATE_f1_score"].append(results["DATE"]["f1"].item())
      history_dict["LOC_f1_score"].append(results["LOC"]["f1"].item())
      history_dict["MISC_f1_score"].append(results["MISC"]["f1"].item())
      history_dict["ORG_f1_score"].append(results["ORG"]["f1"].item())
      history_dict["PER_f1_score"].append(results["PER"]["f1"].item())
      history_dict["Model_f1_score"].append(results["overall_f1"].item())

      history_dict["DATE_precision"].append(results["DATE"]["precision"].item())
      history_dict["LOC_precision"].append(results["LOC"]["precision"].item())
      history_dict["MISC_precision"].append(results["MISC"]["precision"].item())
      history_dict["ORG_precision"].append(results["ORG"]["precision"].item())
      history_dict["PER_precision"].append(results["PER"]["precision"].item())
      history_dict["Model_precision"].append(results["overall_precision"].item())

      history_dict["DATE_recall"].append(results["DATE"]["recall"].item())
      history_dict["LOC_recall"].append(results["LOC"]["recall"].item())
      history_dict["MISC_recall"].append(results["MISC"]["recall"].item())
      history_dict["ORG_recall"].append(results["ORG"]["recall"].item())
      history_dict["PER_recall"].append(results["PER"]["recall"].item())
      history_dict["Model_recall"].append(results["overall_recall"].item())

      result_list.append(results)
      
      print(
          f"epoch {epoch+1}:",
          {
              key: results[f"overall_{key}"]
              for key in ["precision", "recall", "f1", "accuracy"]
          },
      )

  history_dict_folds.append(history_dict)
  print("Training complete for Fold {}!".format(fold + 1))
  print()
  print("=====================================================================================================================")
  print()
print("=====================================================================================================================")
# print(f"Average of Validation Accuracies for {n} Folds is:",round((sum(val_accuracy_folds)/len(val_accuracy_folds)),2))
print("=====================================================================================================================")
print("**********")

"""#### <a>***History Plots***"""

from IPython.display import Image, display
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import seaborn as sns
# history_dict_folds

plt.figure(figsize=(8,5))
plt.style.use("ggplot")
title = "Training and Validation Loss "
plt.suptitle(title, fontsize=18)

plt.plot([round(sum(d['train_loss']) /len(d['train_loss']),2) for d in history_dict_folds], label='Training Loss')
plt.plot([round(sum(d['val_loss'])   /len(d['val_loss']),2) for d in history_dict_folds],   label='Validation Loss')
plt.legend()
plt.xlabel('# of Folds', fontsize=16)
plt.ylabel('Loss', fontsize=16)

plt.show()

plt.figure(figsize=(8,5))
plt.style.use("ggplot")
title = "NER F1 Scores"
plt.suptitle(title, fontsize=18)

plt.plot([round(sum(d['DATE_f1_score'])  /len(d['DATE_f1_score']),2)  for d in history_dict_folds], label='DATE f1_score')
plt.plot([round(sum(d['LOC_f1_score'])   /len(d['LOC_f1_score']),2)   for d in history_dict_folds], label='LOC f1_score')
plt.plot([round(sum(d['ORG_f1_score'])   /len(d['ORG_f1_score']),2)   for d in history_dict_folds], label='ORG f1_score')
plt.plot([round(sum(d['PER_f1_score'])   /len(d['PER_f1_score']),2)   for d in history_dict_folds], label='PER f1_score')
plt.plot([round(sum(d['MISC_f1_score'])  /len(d['MISC_f1_score']),2)  for d in history_dict_folds], label='MISC f1_score')
plt.plot([round(sum(d['Model_f1_score']) /len(d['Model_f1_score']),2) for d in history_dict_folds],label='Model f1_score')
plt.legend()
plt.xlabel('# of Folds', fontsize=16)
plt.ylabel('F1 Score', fontsize=16)

plt.show()

plt.figure(figsize=(8,5))
plt.style.use("ggplot")
title = "NER Precision"
plt.suptitle(title, fontsize=18)


plt.plot([round(sum(d['DATE_precision'])  /len(d['DATE_precision']),2)  for d in history_dict_folds], label='DATE Precision')
plt.plot([round(sum(d['LOC_precision'])   /len(d['LOC_precision']),2)   for d in history_dict_folds], label='LOC Precision')
plt.plot([round(sum(d['ORG_precision'])   /len(d['ORG_precision']),2)   for d in history_dict_folds], label='ORG Precision')
plt.plot([round(sum(d['PER_precision'])   /len(d['PER_precision']),2)   for d in history_dict_folds], label='PER Precision')
plt.plot([round(sum(d['MISC_precision'])  /len(d['MISC_precision']),2)  for d in history_dict_folds], label='MISC Precision')
plt.plot([round(sum(d['Model_precision']) /len(d['Model_precision']),2) for d in history_dict_folds], label='Model Precision')
plt.legend()
plt.xlabel('# of Folds', fontsize=16)
plt.ylabel('Precision', fontsize=16)

plt.show()

plt.figure(figsize=(8,5))
plt.style.use("ggplot")
title = "NER Recall"
plt.suptitle(title, fontsize=18)

plt.plot([round(sum(d['DATE_recall'])  /len(d['DATE_recall']),2)  for d in history_dict_folds], label='DATE Recall')
plt.plot([round(sum(d['LOC_recall'])   /len(d['LOC_recall']),2)   for d in history_dict_folds], label='LOC Recall')
plt.plot([round(sum(d['ORG_recall'])   /len(d['ORG_recall']),2)   for d in history_dict_folds], label='ORG Recall')
plt.plot([round(sum(d['PER_recall'])   /len(d['PER_recall']),2)   for d in history_dict_folds], label='PER Recall')
plt.plot([round(sum(d['MISC_recall'])  /len(d['MISC_recall']),2)  for d in history_dict_folds], label='MISC Recall')
plt.plot([round(sum(d['Model_recall']) /len(d['Model_recall']),2) for d in history_dict_folds], label='Model Recall')

plt.legend()
plt.xlabel('# of Epochs', fontsize=16)
plt.ylabel('Recall', fontsize=16)

plt.show()

"""#### <a>***Evaluate the Model on the Test Data***"""

test_instance = next(iter(test_dataloader))
while True:
  instance = next(iter(test_dataloader))
  unique_labels = set(instance['labels'].tolist()[0])
  if len(unique_labels) > 2:
    test_instance = instance
    break

outputs = model(**test_instance)

predictions = outputs.logits.argmax(dim=-1)
labels = test_instance["labels"]

# Necessary to pad predictions and labels for being gathered
predictions = accelerator.pad_across_processes(predictions, dim=1, pad_index=-100)
labels = accelerator.pad_across_processes(labels, dim=1, pad_index=-100)

predictions_gathered = accelerator.gather(predictions)
labels_gathered = accelerator.gather(labels)

true_predictions, true_labels = postprocess(predictions_gathered, labels_gathered)

# Prediction

y_true = []
y_pred = []

model.eval()
for batch in test_dataloader:

  with torch.no_grad():
    outputs = model(**batch)

  predictions = outputs.logits.argmax(dim=-1)
  labels = batch["labels"]

  # Necessary to pad predictions and labels for being gathered
  predictions = accelerator.pad_across_processes(predictions, dim=1, pad_index=-100)
  labels = accelerator.pad_across_processes(labels, dim=1, pad_index=-100)

  predictions_gathered = accelerator.gather(predictions)
  labels_gathered = accelerator.gather(labels)


  true_labels, true_predictions = postprocess(predictions_gathered, labels_gathered)

  y_true +=  [tag for entry in true_labels for tag in entry]
  y_pred +=  [tag for entry in true_predictions for tag in entry]

def replace_all(text, dic):
    for i, j in dic.items():
        text = text.replace(i, j)
    return text

d = {'B-DATE':"DATE", 'B-LOC':"LOC", 'B-ORG':"ORG", 'I-ORG':"ORG", 'I-PER':"PER", 
     'B-MISC':"MISC", 'B-PER':"PER", 'I-LOC':"LOC", 'I-DATE':"DATE", 'I-MISC':"MISC"}

y_true_N= [replace_all(s, d) for s in y_true]
y_pred_N= [replace_all(s, d) for s in y_pred]

"""#### <a>***Confusion Matrix***"""

from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay

cm = confusion_matrix(y_true_N, y_pred_N, labels=label_names)

fig, ax = plt.subplots(figsize=(8,5))
disp = ConfusionMatrixDisplay.from_predictions(y_true_N, y_pred_N, ax=ax, cmap='Blues')
plt.show()

from seqeval import metrics

print(metrics.classification_report([y_true], [y_pred]))

"""#### <a>**Save Model**"""

model.save_pretrained('models/fintuned/')
