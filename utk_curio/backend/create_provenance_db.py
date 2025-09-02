import sqlite3
import sys
import os

def initialize_db(db_path="provenance.db"):
    # Ensure the directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True) if os.path.dirname(db_path) else None

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    commands = [
        "CREATE TABLE IF NOT EXISTS user (user_id integer primary key, user_name varchar(200), user_type varchar(20), user_IP varchar(20));",
        "CREATE TABLE IF NOT EXISTS versionTransaction (transaction_id integer primary key, transaction_date date, user_id integer, CONSTRAINT fk_trans_user FOREIGN KEY (user_id) REFERENCES user(user_id));",
        "CREATE TABLE IF NOT EXISTS version (version_id integer primary key, version_number varchar(10), transaction_id integer, CONSTRAINT fk_ver_trans FOREIGN KEY (transaction_id) REFERENCES versionTransaction(transaction_id));",
        "CREATE TABLE IF NOT EXISTS versionedElement (ve_id integer primary key, version_id integer, previous_ve_id integer, CONSTRAINT fk_ve_prevve FOREIGN KEY (previous_ve_id) REFERENCES versionedElement(ve_id), CONSTRAINT fk_ve_version FOREIGN KEY (version_id) REFERENCES version(version_id));",
        "CREATE TABLE IF NOT EXISTS workflow (workflow_id integer primary key, workflow_name varchar(20), ve_id integer, CONSTRAINT fk_wf_ve FOREIGN KEY (ve_id) REFERENCES versionedElement(ve_id));",
        "CREATE TABLE IF NOT EXISTS attribute (attribute_id integer primary key, attribute_name varchar(200), attribute_type varchar(20));",  
        "CREATE TABLE IF NOT EXISTS relation (relation_id integer primary key, relation_name varchar(200));",
        "CREATE TABLE IF NOT EXISTS attributeRelation (ar_id integer PRIMARY KEY, attribute_id integer, relation_id integer, CONSTRAINT fk_ar_att FOREIGN KEY (attribute_id) REFERENCES attribute(attribute_id), CONSTRAINT fk_ar_rel FOREIGN KEY (relation_id) REFERENCES relation(relation_id));",
        "CREATE TABLE IF NOT EXISTS activity (activity_id integer primary key, workflow_id integer, ve_id integer, activity_name varchar(50), input_relation_id integer, output_relation_id integer, CONSTRAINT fk_act_wf FOREIGN KEY (workflow_id) REFERENCES workflow(workflow_id), CONSTRAINT fk_act_ve FOREIGN KEY (ve_id) REFERENCES versionedElement(ve_id), CONSTRAINT fk_act_rel_in FOREIGN KEY (input_relation_id) REFERENCES relation(relation_id), CONSTRAINT fk_act_rel_out FOREIGN KEY (output_relation_id) REFERENCES relation(relation_id));",
        "CREATE TABLE IF NOT EXISTS workflowExecution (workflowexec_id integer PRIMARY KEY, workflow_id integer, workflowexec_start_time time, workflowexec_end_time time, int_id integer, CONSTRAINT fk_wfe_wf FOREIGN KEY (workflow_id) REFERENCES workflow(workflow_id), CONSTRAINT fk_wfe_int FOREIGN KEY (int_id) REFERENCES interaction(int_id));",
        "CREATE TABLE IF NOT EXISTS relationInstance (re_id integer primary key, relation_id  integer, original_ri integer, CONSTRAINT fk_ri_rel FOREIGN KEY (relation_id) REFERENCES relation(relation_id), CONSTRAINT fk_ri_or FOREIGN KEY (original_ri) REFERENCES relationInstance(re_id));",
        "CREATE TABLE IF NOT EXISTS attributeValue (av_id integer primary key, attribute_id integer, ri_id integer, value TEXT, CONSTRAINT fk_av_ri FOREIGN KEY  (ri_id) REFERENCES relationInstance(ri_id));",
        "CREATE TABLE IF NOT EXISTS activityExecution (activityexec_id integer PRIMARY KEY, activity_id integer, workflowexec_id integer, activityexec_start_time time, activityexec_end_time time, input_ri_id integer, output_ri_id integer, activity_source_code varchar(2000), CONSTRAINT fk_actexec_wfexec FOREIGN KEY (workflowexec_id) REFERENCES workflowExecution(workflowexec_id), CONSTRAINT fk_actexec_act FOREIGN KEY (activity_id) REFERENCES activity(activity_id), CONSTRAINT fk_actexec_rel_in FOREIGN KEY (input_ri_id) REFERENCES relationInstance(re_id), CONSTRAINT fk_actexec_rel_out FOREIGN KEY (output_ri_id) REFERENCES relationInstance(re_id));",
        "CREATE TABLE IF NOT EXISTS visualization (vis_id integer PRIMARY KEY, vis_path varchar(200), vis_content integer, activityexec_id integer, CONSTRAINT fk_vis_actexec FOREIGN KEY (activityexec_id) REFERENCES activityExecution(activityexec_id));",
        "CREATE TABLE IF NOT EXISTS interaction (int_id integer PRIMARY KEY, int_time date, user_id integer, vis_id integer, CONSTRAINT fk_int_user FOREIGN KEY (user_id) REFERENCES user(user_id), CONSTRAINT fk_int_vis FOREIGN KEY (vis_id) REFERENCES visualization(vis_id));",
        "CREATE TABLE IF NOT EXISTS attributeValueChange (avc_id integer PRIMARY KEY, av_id integer, int_id integer, old_value TEXT NOT NULL, CONSTRAINT fk_avc_av FOREIGN KEY (av_id) REFERENCES attributeValue(av_id), CONSTRAINT fk_avc_int FOREIGN KEY (int_id) REFERENCES interaction(int_id));"
    ]

    for command in commands:
        cursor.execute(command)
        conn.commit()
    conn.close()

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "provenance.db"
    initialize_db(db_path)




