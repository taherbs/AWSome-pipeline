from aws_cdk import (
    aws_codepipeline as codepipeline,
    aws_codebuild as codebuild,
    aws_codepipeline_actions as codepipeline_actions,
    aws_kms as kms,
    aws_s3 as s3,
    aws_iam as iam,
    aws_codedeploy as codedeploy,
    core
)

class PipelineStack(core.Stack):

    def __init__(self, scope: core.Construct, id: str, *, git_token_key="", github_owner="",
                 github_repo="", github_branch="", alb="", **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        deploy_app_stg = codedeploy.EcsApplication(self, id="stg")

        deploy_group_stg = codedeploy.EcsDeploymentGroup.from_ecs_deployment_group_attributes(
            self,
            id="ciao",
            application=deploy_app_stg,
            deployment_group_name="banana"
        )

        role = iam.Role(
            self,
            "Role",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com")
        )

        role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("AdministratorAccess")
        )

        cdk_project = codebuild.PipelineProject(
            self,
            "Codebuild",
            build_spec=codebuild.BuildSpec.from_source_filename("codebuild/buildspec.yaml"),
            cache=codebuild.Cache.bucket(s3.Bucket(self, "Bucket")),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_2_0,
                privileged=True
                ),
            role=role
        )

        source_output = codepipeline.Artifact()
        staging_output = codepipeline.Artifact()
        production_output = codepipeline.Artifact()

        source_action = codepipeline_actions.GitHubSourceAction(
            action_name="GitHub_Source",
            owner=github_owner,
            repo=github_repo,
            branch=github_branch,
            oauth_token=core.SecretValue.secrets_manager(git_token_key),
            output=source_output
        )

        staging_action_infra = codepipeline_actions.CodeBuildAction(
            action_name="StagingInfra",
            project=cdk_project,
            input=source_output,
            outputs=[staging_output],
            environment_variables={
                "ENV": {"value": "stg"}
            },
            run_order=1
        )

        staging_action_ecs = codepipeline_actions.CodeDeployEcsDeployAction(
            action_name="StagingEcs",
            run_order=2,
            deployment_group=deploy_group_stg,
            app_spec_template_input=staging_output,
            task_definition_template_input=staging_output
        )

        manual_approval_action = codepipeline_actions.ManualApprovalAction(
            action_name="Approve"
        )

        production_action_infra = codepipeline_actions.CodeBuildAction(
            action_name="ProductionInfra",
            project=cdk_project,
            input=source_output,
            outputs=[production_output],
            environment_variables={
                "ENV": {"value": "prd"}
            },
            run_order=1
        )

        production_action_ecs = codepipeline_actions.CodeDeployEcsDeployAction(
            action_name="ProductionEcs",
            run_order=2,
            deployment_group=deploy_group_stg,
            app_spec_template_input=production_output,
            task_definition_template_input=production_output
        )

        key = kms.Key(self, "key")
        bucket = s3.Bucket(self, "bucket_artifacts", encryption_key=key)
        pipeline = codepipeline.Pipeline(self, "Pipeline", artifact_bucket=bucket)
        pipeline.add_stage(stage_name="Source", actions=[source_action])
        pipeline.add_stage(stage_name="Staging", actions=[staging_action_infra, staging_action_ecs])
        pipeline.add_stage(stage_name="Approval", actions=[manual_approval_action])
        pipeline.add_stage(stage_name="Production", actions=[production_action_infra, production_action_ecs])